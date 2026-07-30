"""Adapter: live account state → a ``tradexa.portfolio.Portfolio``.

This is the seam that keeps portfolio mathematics out of the execution engine.
Everything here is translation — reading the paper engine, the ledger and the
broker registry, and expressing what they hold in the engine's own vocabulary.
No number is computed here; the engine computes all of them.

That split is the point. Adding a second exchange means adding a
``VenueSnapshot`` to this file. It means changing nothing in the engine, and
nothing in the arithmetic that produces equity, exposure or Sharpe.

Two things this file will not do:

**It will not invent a mark.** A position whose price could not be fetched is
passed through unmarked, and the engine reports equity as unavailable. Falling
back to the entry price would silently report an open loss as break-even.

**It will not present an unreadable broker as an empty one.** A configured live
broker with no balance API appears as an unreachable venue with the reason
attached, so the gap is visible on the page rather than absorbed into a total
that quietly describes the paper account alone.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from tradexa.portfolio import (
    ClosedTrade, Direction, EquityPoint, Portfolio, PortfolioEngine,
    PositionSnapshot, VenueKind, VenueSnapshot,
)

#: The paper account's venue name. Stable because it is a dictionary key in
#: every payload this module produces.
PAPER_VENUE = "paper"


def _parse(ts: Any) -> Optional[datetime]:
    """ISO-8601 out of the ledger, or ``None``.

    Naive timestamps are read as UTC — the ledger writes UTC throughout, and a
    naive datetime compared against an aware one raises rather than sorting, so
    a single naive row would take down the whole curve.
    """
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    if not ts:
        return None
    try:
        parsed = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def paper_venue(paper, marks: Optional[dict[str, float]] = None) -> VenueSnapshot:
    """The paper account as one venue.

    ``cash`` is the paper engine's own balance and the open notional is carried
    as committed margin, so ``equity == cash + unrealised`` matches
    ``PaperExecutionEngine.equity()`` exactly. Two definitions of equity for one
    account is how a portfolio page and an account page start disagreeing.
    """
    marks = marks or {}
    positions = tuple(
        PositionSnapshot(
            symbol=p["symbol"],
            direction=(Direction.LONG if p.get("side") == "long" else Direction.SHORT),
            qty=float(p.get("size") or 0.0),
            entry=float(p.get("entry") or 0.0),
            mark=marks.get(p["symbol"]),
            stop=(float(p["stop"]) if p.get("stop") is not None else None),
            venue=PAPER_VENUE)
        for p in paper.positions())
    return VenueSnapshot(
        venue=PAPER_VENUE, kind=VenueKind.PAPER,
        cash=float(paper.balance()),
        positions=positions,
        used_margin=float(paper.open_notional()),
        max_leverage=1.0,
        realized_pnl=float(paper.realized_pnl()))


#: Venue kinds that are crypto exchanges rather than brokers. The distinction is
#: reported, not acted on — both take the identical path through the engine —
#: but an operator reading a venue list wants to know which is which.
_EXCHANGE_KINDS = {"binance", "bybit", "okx", "kraken", "coinbase", "kucoin"}


def broker_venues(registry) -> tuple[VenueSnapshot, ...]:
    """Configured live brokers and exchanges, as far as they can be read.

    ``BrokerRegistry`` exposes connectivity and order placement — not balances.
    So every live venue here is reported UNREACHABLE with the reason attached.
    That is the honest answer: the platform genuinely cannot see those accounts'
    equity, and a zero would fold a real balance into the totals as nothing.

    A venue with no credentials is NOT included. It is a catalogue entry, not an
    account: the registry lists every venue the platform could support, and
    reporting all four as "unreachable" put four permanent caveats on every
    snapshot, which made ``available`` false forever and trained the reader to
    ignore it. A configured venue that cannot be read is a real gap and does
    appear; an unconfigured one is simply not part of the portfolio.
    """
    if registry is None:
        return ()
    brokers = getattr(registry, "brokers", None) or {}
    out: list[VenueSnapshot] = []
    for kind, broker in brokers.items():
        if kind == PAPER_VENUE:
            continue
        try:
            connected = bool(broker.connected())
        except Exception:  # noqa: BLE001 — a broker that cannot answer is not connected
            connected = False
        if not connected:
            continue
        label = getattr(broker, "name", kind) or kind
        out.append(VenueSnapshot(
            venue=kind,
            kind=(VenueKind.EXCHANGE if kind in _EXCHANGE_KINDS else VenueKind.BROKER),
            reachable=False,
            note=(f"{label}: credentials present, but this integration exposes no "
                  "balance endpoint — its equity is not visible to the platform")))
    return tuple(out)


def realized_equity_curve(paper) -> tuple[EquityPoint, ...]:
    """Equity after each closed trade.

    Realised only: the paper engine records a balance at close, not a series of
    marks, so there is no observation between one close and the next. The
    consequence is stated by the caller rather than hidden — Sharpe and drawdown
    computed from this curve describe trade-to-trade equity, and an open
    position's swing is invisible to them until it closes.

    Deliberately not shared with ``/paper/equity-curve``: that endpoint prepends
    a synthetic point with a null timestamp for the chart's left edge, which is
    a drawing convenience and not an observation. Feeding it to the metrics
    would date the account's opening equity to whenever the request happened.
    """
    closed = sorted((t for t in paper.history() if t.get("closed_at")),
                    key=lambda t: t["closed_at"])
    if not closed:
        return ()
    points: list[EquityPoint] = []
    equity = float(paper.starting_balance)
    opened = _parse(closed[0].get("opened_at"))
    if opened is not None:
        points.append(EquityPoint(opened, equity))
    for t in closed:
        equity += float(t.get("pnl") or 0.0)
        at = _parse(t.get("closed_at"))
        if at is not None:
            points.append(EquityPoint(at, equity))
    return tuple(points)


def closed_trades(paper, venue: str = PAPER_VENUE) -> tuple[ClosedTrade, ...]:
    return tuple(
        ClosedTrade(symbol=t.get("symbol", ""), pnl=float(t.get("pnl") or 0.0),
                    closed_at=_parse(t.get("closed_at")),
                    opened_at=_parse(t.get("opened_at")), venue=venue,
                    rr=(float(t["rr"]) if t.get("rr") is not None else None))
        for t in paper.history() if t.get("closed_at"))


def build_portfolio(*, paper, registry=None, marks: Optional[dict] = None,
                    at: Optional[datetime] = None,
                    base_currency: str = "USD",
                    fx_rates: Optional[dict] = None) -> Portfolio:
    """Assemble the whole book. Reads; computes nothing."""
    return Portfolio(
        venues=(paper_venue(paper, marks),) + broker_venues(registry),
        equity_curve=realized_equity_curve(paper),
        closed_trades=closed_trades(paper),
        base_currency=base_currency,
        fx_rates=fx_rates or {},
        at=at or datetime.now(timezone.utc))


def snapshot(*, paper, registry=None, marks: Optional[dict] = None,
             **kw) -> dict[str, Any]:
    """The portfolio state as a JSON-safe payload.

    Two separate lists travel with the figures, and keeping them apart matters:

    ``notes``  what is MISSING from this snapshot — an unmarked position, an
               unreachable venue, too short a history. Fixable, and they drive
               ``available``.
    ``basis``  how the figures are DERIVED. Permanent properties of the data
               source, true of every snapshot this platform can produce.

    Folding the second into the first was the first version of this function,
    and it made ``available`` false on every call — including a snapshot with
    nothing actually wrong with it. A warning that is always on is one nobody
    reads, which costs more than it buys the first time something is genuinely
    missing.
    """
    portfolio = build_portfolio(paper=paper, registry=registry, marks=marks, **kw)
    state = PortfolioEngine().snapshot(portfolio)
    data = state.as_dict()

    basis = [data.get("sharpe_basis") or ""]
    if portfolio.equity_curve:
        basis.append("equity curve is realised-only (one point per closed "
                     "trade) — Sharpe and drawdown describe trade-to-trade "
                     "equity and do not see an open position's swings")

    notes = list(data.get("notes") or ())
    unmarked = sorted({p.symbol for v in portfolio.venues for p in v.positions
                       if p.mark is None})
    if unmarked:
        notes.append(f"no live price for {', '.join(unmarked)} — marked at "
                     "entry for exposure, excluded from equity")
    data["notes"] = notes
    data["basis"] = [b for b in basis if b]
    data["available"] = not notes
    return data


__all__ = ["PAPER_VENUE", "paper_venue", "broker_venues",
           "realized_equity_curve", "closed_trades", "build_portfolio",
           "snapshot"]
