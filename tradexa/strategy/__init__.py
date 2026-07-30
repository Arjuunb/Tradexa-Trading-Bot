"""Strategies as installable plugins.

    from tradexa.strategy import BaseStrategy, Parameter, ParamType, StrategyMeta

    class MyStrategy(BaseStrategy):
        '''One sentence on what it trades. This becomes the documentation.'''

        meta = StrategyMeta(key="mine", name="My Strategy", version="1.0.0",
                            maturity=Maturity.STABLE)
        parameters = (
            Parameter("lookback", ParamType.INT, default=20, minimum=5,
                      maximum=200, unit="bars", tunable=True,
                      optimise=(10, 20, 50)),
        )

        def generate(self, bar):
            ...

Drop that in the plugins directory and it is installed: discovered on boot,
listed in the API with its metadata and generated documentation, validated on
construction, and sweepable by the optimiser. Nothing in the trading engine is
edited to add it.
"""
from tradexa.strategy.base import BaseStrategy, StrategyParameterError
from tradexa.strategy.discovery import (
    ENTRY_POINT_GROUP, discover_all, discover_directory, discover_entry_points,
    discover_package, register_module, strategies_in,
)
from tradexa.strategy.optimisation import (
    Candidate, DEFAULT_MAX_CANDIDATES, OptimisationError, OptimisationResult,
    candidates, grid_search, split,
)
from tradexa.strategy.metadata import (
    Maturity, ParamType, Parameter, StrategyMeta, ValidationIssue,
    ValidationResult, validate,
)
from tradexa.strategy.registry import (
    DuplicateStrategyError, InvalidStrategyError, StrategyRegistry,
    StrategyRegistryError, UnknownStrategyError, default_registry,
)

__all__ = [
    "BaseStrategy", "StrategyParameterError",
    "StrategyMeta", "Parameter", "ParamType", "Maturity",
    "ValidationResult", "ValidationIssue", "validate",
    "StrategyRegistry", "default_registry", "StrategyRegistryError",
    "DuplicateStrategyError", "InvalidStrategyError", "UnknownStrategyError",
    "Candidate", "OptimisationResult", "OptimisationError", "candidates",
    "grid_search", "split", "DEFAULT_MAX_CANDIDATES",
    "ENTRY_POINT_GROUP", "discover_all", "discover_directory",
    "discover_entry_points", "discover_package", "register_module",
    "strategies_in",
]
