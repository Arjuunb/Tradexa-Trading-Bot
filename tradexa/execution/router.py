"""Smart order routing: choosing where an order goes, and where it goes next.

Routing produces an ORDER of venues, not a single choice. The distinction is
the whole feature: a router that returns one venue makes failover someone
else's problem, and "someone else" ends up re-implementing the ranking in the
retry loop.

Ranking is deliberately explainable. Each candidate carries the reason it sits
where it does, because "why did that order go to Bybit?" is a question asked
after a bad fill, when the health data that drove the decision has already moved
on.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional, Sequence

from bot.types import Order
from tradexa.execution.reliability import CircuitBreaker, CircuitState
from tradexa.execution.venues import VenueCapabilities, VenueHealth, VenueState


class RoutingStrategy(str, Enum):
    """How to break ties between usable venues."""

    #: Lowest observed p95 latency. For orders where getting there first matters.
    FASTEST = "fastest"
    #: Lowest taker fee. For size that will cross the spread anyway.
    CHEAPEST = "cheapest"
    #: Declared preference order, health permitting.
    PREFERRED = "preferred"
    #: Fastest among the healthiest — latency, but never onto a degraded venue
    #: while a healthy one exists. The default, because a fast venue that is
    #: half-failing is not fast.
    BALANCED = "balanced"


@dataclass
class VenueProfile:
    """Everything the router knows about one venue."""

    name: str
    health: VenueHealth
    capabilities: VenueCapabilities = field(default_factory=VenueCapabilities)
    breaker: Optional[CircuitBreaker] = None
    #: Lower is preferred under PREFERRED, and breaks ties elsewhere.
    preference: int = 0
    #: Symbols this venue can trade. Empty means no restriction.
    symbols: tuple[str, ...] = ()
    enabled: bool = True

    def supports(self, symbol: str) -> bool:
        return not self.symbols or symbol in self.symbols


@dataclass(frozen=True)
class Candidate:
    """One venue's place in the routing decision, and why."""

    venue: str
    rank: int
    score: float
    reason: str
    eligible: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {"venue": self.venue, "rank": self.rank, "score": round(self.score, 6),
                "reason": self.reason, "eligible": self.eligible}


@dataclass(frozen=True)
class Route:
    """Where an order should go, and where it should go if that fails."""

    order_symbol: str
    strategy: RoutingStrategy
    candidates: tuple[Candidate, ...] = ()
    excluded: tuple[Candidate, ...] = ()

    @property
    def primary(self) -> Optional[str]:
        return self.candidates[0].venue if self.candidates else None

    @property
    def fallbacks(self) -> tuple[str, ...]:
        return tuple(c.venue for c in self.candidates[1:])

    @property
    def venues(self) -> tuple[str, ...]:
        return tuple(c.venue for c in self.candidates)

    def explain(self) -> str:
        if not self.candidates:
            reasons = "; ".join(f"{c.venue}: {c.reason}" for c in self.excluded)
            return f"no venue can take {self.order_symbol} ({reasons or 'none configured'})"
        chain = " → ".join(c.venue for c in self.candidates)
        return (f"{self.order_symbol} via {chain} [{self.strategy.value}] — "
                f"{self.candidates[0].reason}")

    def as_dict(self) -> dict[str, Any]:
        return {"symbol": self.order_symbol, "strategy": self.strategy.value,
                "primary": self.primary, "fallbacks": list(self.fallbacks),
                "candidates": [c.as_dict() for c in self.candidates],
                "excluded": [c.as_dict() for c in self.excluded]}


class SmartOrderRouter:
    """Ranks venues for an order. Holds no connections and places nothing."""

    def __init__(self, profiles: Sequence[VenueProfile] = (), *,
                 strategy: RoutingStrategy = RoutingStrategy.BALANCED) -> None:
        self._profiles: dict[str, VenueProfile] = {p.name: p for p in profiles}
        self.strategy = strategy

    # ---------------------------------------------------------------- manage
    def add(self, profile: VenueProfile) -> VenueProfile:
        self._profiles[profile.name] = profile
        return profile

    def remove(self, name: str) -> None:
        self._profiles.pop(name, None)

    def profile(self, name: str) -> Optional[VenueProfile]:
        return self._profiles.get(name)

    @property
    def venues(self) -> tuple[str, ...]:
        return tuple(self._profiles)

    # ----------------------------------------------------------------- route
    def route(self, order: Order, *,
              strategy: Optional[RoutingStrategy] = None,
              require: Optional[Callable[[VenueProfile], bool]] = None) -> Route:
        """Rank the venues that can take this order.

        ``require`` filters on a capability the order needs — reduce-only, a
        leverage floor, amendment support. Expressed as a predicate rather than
        a flags argument so a caller can ask for something the router was never
        taught about, which is most of what a new venue brings.
        """
        strategy = strategy or self.strategy
        eligible: list[tuple[VenueProfile, float, str]] = []
        excluded: list[Candidate] = []

        for profile in self._profiles.values():
            reason = self._ineligible(profile, order, require)
            if reason:
                excluded.append(Candidate(profile.name, -1, 0.0, reason, eligible=False))
                continue
            score, why = self._score(profile, strategy)
            eligible.append((profile, score, why))

        # Highest score first; ties broken by declared preference, then name, so
        # the same inputs always produce the same order. A router whose output
        # depends on dict ordering makes an incident impossible to reconstruct.
        eligible.sort(key=lambda t: (-t[1], t[0].preference, t[0].name))
        candidates = tuple(
            Candidate(profile.name, rank, score, why)
            for rank, (profile, score, why) in enumerate(eligible))
        return Route(order_symbol=order.symbol, strategy=strategy,
                     candidates=candidates, excluded=tuple(excluded))

    # --------------------------------------------------------------- private
    @staticmethod
    def _ineligible(profile: VenueProfile, order: Order,
                    require: Optional[Callable[[VenueProfile], bool]]) -> str:
        """Why this venue cannot take the order, or "" if it can."""
        if not profile.enabled:
            return "disabled"
        if profile.health.state is VenueState.DISABLED:
            return f"venue disabled{f' ({profile.health.note})' if profile.health.note else ''}"
        if profile.health.state is VenueState.DOWN:
            return f"venue down: {profile.health.last_error or 'no successful request'}"
        if profile.breaker is not None and profile.breaker.state is CircuitState.OPEN:
            return f"circuit open until {profile.breaker.open_until}"
        if not profile.supports(order.symbol):
            return f"does not trade {order.symbol}"
        if require is not None and not require(profile):
            return "does not meet the order's capability requirement"
        return ""

    @staticmethod
    def _score(profile: VenueProfile, strategy: RoutingStrategy) -> tuple[float, str]:
        """Higher is better. Returns the score and the reason for it."""
        health = profile.health
        latency = health.latency(95)
        fee = profile.capabilities.taker_fee_bps

        if strategy is RoutingStrategy.PREFERRED:
            return -float(profile.preference), f"preference {profile.preference}"

        if strategy is RoutingStrategy.CHEAPEST:
            return -fee, f"taker fee {fee:.2f} bps"

        if strategy is RoutingStrategy.FASTEST:
            if latency is None:
                # An unmeasured venue is not the fastest one. Ranking it first
                # would send every order to whichever venue has never been used,
                # which is also the one nothing is known about.
                return -1e6 + -float(profile.preference), "no latency samples yet"
            return -latency, f"p95 {latency:.1f}ms"

        # BALANCED: health first, then latency. A degraded venue is never
        # preferred over a healthy one however fast it looks — its speed is
        # measured on the requests that succeeded.
        health_score = 1000.0 if health.state is VenueState.UP else 0.0
        if latency is None:
            return health_score - 500.0, f"{health.state.value}, no latency samples"
        penalty = health.failure_rate * 100.0
        return (health_score - latency / 10.0 - penalty,
                f"{health.state.value}, p95 {latency:.1f}ms, "
                f"{health.failure_rate * 100:.1f}% failures")


__all__ = ["RoutingStrategy", "VenueProfile", "Candidate", "Route",
           "SmartOrderRouter"]
