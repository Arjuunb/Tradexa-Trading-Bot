# Strategy plugins

Drop a `.py` file in this directory and it is installed: discovered at boot,
listed by `GET /strategies` with its metadata and generated documentation,
validated when constructed, and sweepable by the optimiser.

Nothing in the trading engine is edited to add, remove or version a strategy.

## The shortest complete plugin

```python
from typing import Optional

from bot.types import Bar, Signal, SignalType
from tradexa.strategy import Maturity, ParamType, Parameter, StrategyMeta

from strategies.base_strategy import ATR_PARAMETERS, HubStrategy


class MyStrategy(HubStrategy):
    """One sentence on what it trades. This becomes the documentation."""

    name = "mine"
    label = "My Strategy"

    meta = StrategyMeta(
        key="mine", name="My Strategy", version="1.0.0",
        description="What it does, in a line.",
        author="you", maturity=Maturity.EXPERIMENTAL,
        asset_classes=("crypto",), timeframes=("1h",))

    parameters = ATR_PARAMETERS + (
        Parameter("lookback", ParamType.INT, default=20, minimum=5, maximum=200,
                  unit="bars", tunable=True, optimise=(10, 20, 50),
                  description="How far back the breakout is measured."),
    )

    def __init__(self, symbol: str, *, lookback: int = 20, **params):
        super().__init__(symbol, lookback=lookback, **params)

    def generate(self, bar: Bar) -> Optional[Signal]:
        n = self.params["lookback"]
        if len(self.bars) <= n:
            return None
        high = max(b.high for b in self.bars[-n - 1:-1])
        if bar.close > high:
            return self._signal(bar, SignalType.LONG, f"closed above the {n}-bar high")
        return None
```

`_signal` builds the entry/stop/target bracket from ATR using the parameters
declared in `ATR_PARAMETERS`, so a plugin does not do its own risk arithmetic.

## What each piece buys you

| Declaration | What it enables |
|---|---|
| `meta.key` | how a saved bot configuration finds this code. Must be unique |
| `meta.version` | results are only comparable within a version. Semver, enforced |
| `meta.maturity` | `STABLE` is what puts it in the bot builder. Start `EXPERIMENTAL` |
| `meta.requires` | constructor arguments with no default — keeps it out of the builder |
| `parameters` | types, bounds, units and descriptions the API and UI render |
| `tunable` + `optimise` | the values an optimiser is allowed to try |
| `validate()` | cross-parameter rules, e.g. fast must be below slow |
| the docstring | becomes the generated reference page |

## Maturity

A new plugin should start `EXPERIMENTAL`. It is fully installed at that point —
discoverable, documented, backtestable — it simply is not offered as a live bot
option. Raise it to `STABLE` when it has a track record you would stand behind.
That is a change to your file, not to the platform.

## When a plugin is broken

A file that fails to import does not stop the others loading. The failure is
printed at boot as `[plugins] <file>: <error>` and returned by
`GET /strategies` under `errors`, with the line that failed.

Two plugins claiming the same `meta.key` is an error, not a silent overwrite —
keys are how saved bots find their code, and last-import-wins would quietly
change what a running bot executes.

## Installing a packaged strategy

A distributable strategy is a pip package declaring an entry point:

```toml
[project.entry-points."tradexa.strategies"]
my_pack = "my_pack.strategies"
```

`pip install` it and it is discovered on the next boot. The entry point may
point at a single class or a module holding several.

## Where this directory lives

`automation-hub/plugins/` by default; set `HUB_PLUGINS_DIR` to point elsewhere
— a mounted disk, for instance, so installed plugins survive a redeploy.
