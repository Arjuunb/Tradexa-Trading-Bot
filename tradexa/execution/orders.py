"""The order lifecycle: partial fills, amendments, cancel/replace.

An order is not a request that succeeds or fails. It is a thing with a life:
submitted, partly filled, amended, partly filled again, cancelled with a
remainder, replaced. Modelling it as a boolean is what forces every caller to
reconstruct that history from logs.

Two rules run through this file.

**Fills accumulate; they never overwrite.** Venues report fills incrementally
and they report them more than once — a websocket update and a REST poll will
happily deliver the same fill twice. ``apply_fill`` is keyed on the venue's fill
id and ignores a repeat, because adding it again would inflate the position and
the average price by exactly the amount nobody notices until reconciliation.

**Cancel/replace is one operation with a remainder.** Replacing a partly filled
order means cancelling the rest and submitting a NEW order for what is left —
not for the original quantity. Getting that wrong doubles the intended size, and
it is the classic way a "just amend it" convenience turns into an oversized
position.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from bot.types import Order, Side


class OrderStatus(str, Enum):
    PENDING = "pending"           # created locally, not yet acknowledged
    OPEN = "open"                 # live at the venue, unfilled
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    #: The venue's answer is unknown — a timeout, a dropped socket. NOT an
    #: error state: an unknown order may well be live, and treating it as failed
    #: is how a position gets opened twice.
    UNKNOWN = "unknown"
    EXPIRED = "expired"

    @property
    def terminal(self) -> bool:
        return self in (OrderStatus.FILLED, OrderStatus.CANCELLED,
                        OrderStatus.REJECTED, OrderStatus.EXPIRED)


@dataclass(frozen=True)
class FillEvent:
    """One execution against an order, as the venue reported it."""

    fill_id: str
    qty: float
    price: float
    at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    fee: float = 0.0
    liquidity: str = ""            # "maker" | "taker" | ""

    @property
    def notional(self) -> float:
        return self.qty * self.price


@dataclass(frozen=True)
class Amendment:
    """A requested change to a resting order, and whether it landed."""

    at: datetime
    qty: Optional[float] = None
    limit_price: Optional[float] = None
    applied: bool = False
    #: Set when the venue cannot amend and the engine fell back to
    #: cancel/replace, so the audit trail says which happened.
    via_replace: bool = False
    reason: str = ""


@dataclass
class OrderRecord:
    """One order, from intent to terminal state.

    The engine's local truth. Reconciliation compares it against the venue's,
    and any disagreement is reported rather than resolved by assumption.
    """

    client_id: str
    order: Order
    venue: str = ""
    broker_order_id: Optional[str] = None
    status: OrderStatus = OrderStatus.PENDING
    fills: list[FillEvent] = field(default_factory=list)
    amendments: list[Amendment] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    #: Set when this order replaced another, so a chain can be followed.
    replaces: Optional[str] = None
    replaced_by: Optional[str] = None
    error: str = ""
    context: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._lock = threading.RLock()
        self._fill_ids: set[str] = {f.fill_id for f in self.fills}

    # ------------------------------------------------------------- quantities
    @property
    def requested_qty(self) -> float:
        return float(self.order.qty)

    @property
    def filled_qty(self) -> float:
        return sum(f.qty for f in self.fills)

    @property
    def remaining_qty(self) -> float:
        # Clamped at zero: an overfill is a venue bug or a duplicated fill, and
        # a negative remainder would make a replace submit a negative quantity.
        return max(0.0, self.requested_qty - self.filled_qty)

    @property
    def average_price(self) -> Optional[float]:
        """Volume-weighted, or ``None`` before the first fill.

        ``None`` rather than 0.0 or the limit price: an unfilled order has no
        execution price, and substituting the limit reports a fill that has not
        happened.
        """
        filled = self.filled_qty
        if filled <= 0:
            return None
        return sum(f.notional for f in self.fills) / filled

    @property
    def fees(self) -> float:
        return sum(f.fee for f in self.fills)

    @property
    def is_partial(self) -> bool:
        return 0 < self.filled_qty < self.requested_qty

    # ---------------------------------------------------------------- updates
    def apply_fill(self, fill: FillEvent) -> bool:
        """Record a fill. Returns False if it was a duplicate.

        Deduplicated on the venue's fill id because venues deliver the same fill
        more than once — a websocket push and a REST reconciliation poll both
        report it, and a second application inflates both the position and the
        average price.
        """
        with self._lock:
            if fill.fill_id in self._fill_ids:
                return False
            self._fill_ids.add(fill.fill_id)
            self.fills.append(fill)
            self.updated_at = datetime.now(timezone.utc)
            if self.remaining_qty <= 1e-12:
                self.status = OrderStatus.FILLED
            elif self.filled_qty > 0:
                self.status = OrderStatus.PARTIALLY_FILLED
            return True

    def mark(self, status: OrderStatus, *, error: str = "",
             broker_order_id: Optional[str] = None) -> None:
        with self._lock:
            # A terminal FILLED is never downgraded by a late status message.
            # Venues send stale updates out of order, and a "cancelled" arriving
            # after the fill it lost the race to would erase a real position.
            if self.status is OrderStatus.FILLED and status is not OrderStatus.FILLED:
                return
            self.status = status
            self.updated_at = datetime.now(timezone.utc)
            if error:
                self.error = error
            if broker_order_id:
                self.broker_order_id = broker_order_id

    def record_amendment(self, amendment: Amendment) -> None:
        with self._lock:
            self.amendments.append(amendment)
            self.updated_at = datetime.now(timezone.utc)
            if amendment.applied and amendment.qty is not None:
                # The order's own quantity changes, so `remaining_qty` stays
                # meaningful. An amendment that changed the venue's view but not
                # ours would make every later calculation wrong by the difference.
                self.order.qty = float(amendment.qty)
            if amendment.applied and amendment.limit_price is not None:
                self.order.limit_price = float(amendment.limit_price)

    def replacement_order(self, *, limit_price: Optional[float] = None,
                          qty: Optional[float] = None) -> Order:
        """The order that should replace this one.

        Sized to the REMAINDER by default, not the original quantity. Replacing
        a half-filled order with a full-size one is how a cancel/replace
        convenience becomes a double position, and it is invisible until the
        book is reconciled.
        """
        remaining = self.remaining_qty if qty is None else float(qty)
        return Order(symbol=self.order.symbol, side=self.order.side,
                     qty=remaining, order_type=self.order.order_type,
                     limit_price=(limit_price if limit_price is not None
                                  else self.order.limit_price),
                     stop_loss=self.order.stop_loss,
                     take_profit=self.order.take_profit)

    # ------------------------------------------------------------------- view
    def as_dict(self) -> dict[str, Any]:
        return {
            "client_id": self.client_id, "venue": self.venue,
            "broker_order_id": self.broker_order_id, "status": self.status.value,
            "symbol": self.order.symbol,
            "side": getattr(self.order.side, "value", self.order.side),
            "requested_qty": self.requested_qty, "filled_qty": self.filled_qty,
            "remaining_qty": self.remaining_qty,
            "average_price": self.average_price, "fees": self.fees,
            "fills": [{"id": f.fill_id, "qty": f.qty, "price": f.price,
                       "at": f.at.isoformat(), "fee": f.fee,
                       "liquidity": f.liquidity} for f in self.fills],
            "amendments": [{"at": a.at.isoformat(), "qty": a.qty,
                            "limit_price": a.limit_price, "applied": a.applied,
                            "via_replace": a.via_replace, "reason": a.reason}
                           for a in self.amendments],
            "replaces": self.replaces, "replaced_by": self.replaced_by,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "error": self.error,
        }


def signed_qty(record: OrderRecord) -> float:
    """Filled quantity, signed by side. The unit position reconciliation uses."""
    side = getattr(record.order.side, "value", record.order.side)
    return record.filled_qty * (1.0 if str(side).lower() in ("buy", "long") else -1.0)


__all__ = ["OrderStatus", "FillEvent", "Amendment", "OrderRecord", "signed_qty",
           "Order", "Side"]
