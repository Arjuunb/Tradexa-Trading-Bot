"""Compatibility shim — TradeManager now lives in the shared TradeCore package.

Sprint 4 S4.5a moved the trade-management core to ``bot/tradecore/trade_manager
.py`` so BOTH engine families can share it: ``bot`` is the repo-root package that
is importable everywhere (it is the one mapped by the editable install), whereas
``automation-hub/`` is not on ``sys.path`` for the root-level test suite.

Every existing ``from services.trade_manager import ...`` keeps working through
this re-export, so the move is behaviour-preserving. New code should import from
``bot.tradecore.trade_manager`` (or ``bot.tradecore``) directly.
"""
from bot.tradecore.trade_manager import Action, ManagedTrade, TradeManager

__all__ = ["Action", "ManagedTrade", "TradeManager"]
