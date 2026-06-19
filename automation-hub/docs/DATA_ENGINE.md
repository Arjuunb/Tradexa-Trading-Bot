# Historical Data Engine (real Binance candles)

A reusable market-data service that fetches **real** OHLCV history from Binance's
public REST API and caches it in a local SQLite database. There is **no
synthetic price generation** in this path — if neither the cache nor the network
has data, callers get an explicit "unavailable", never a fabricated candle.

## Supported

- Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `XRPUSDT`
- Timeframes: `1w`, `1d`, `4h`, `15m`, `5m`

## Populate the cache (run once with network access)

```bash
# every symbol × timeframe
python -m data.historical

# one symbol/timeframe with a target candle count
python -m data.historical BTCUSDT 5m 5000
```

Or via the API (secret-gated):

```bash
curl -X POST "$API/data/sync?symbol=BTCUSDT&timeframe=4h&target_candles=3000" \
     -H "X-Webhook-Secret: $SECRET"
curl -X POST "$API/data/sync-all" -H "X-Webhook-Secret: $SECRET"
curl "$API/data/coverage"     # what's cached
```

## How the rest of the system uses it

`data.market_data.get_bars()` now resolves data **real-first**:

1. **local store (real)** — cached Binance candles (this engine)
2. **live (ccxt)** — when `HUB_USE_LIVE_DATA=1`
3. **bundled sample** — the real CSV shipped in the repo
4. **synthetic** — deterministic, demo/tests only

Set **`HUB_REQUIRE_REAL_DATA=1`** in production to forbid the bundled/synthetic
fallbacks entirely: `get_bars` then returns an empty result + "unavailable
(real data required — run /data/sync)" instead of any non-real data. The replay,
multi-timeframe, regime, quality and evolution engines all read through
`get_bars`, so once the cache is populated they run on genuine market data —
including real Weekly/Daily context.

## Config

| Env | Default | Meaning |
|-----|---------|---------|
| `HUB_MARKET_DB` | `logs/market_data.db` | SQLite cache location |
| `HUB_REQUIRE_REAL_DATA` | off | forbid synthetic/bundled fallback |
| `HUB_EXCHANGE` | `binance` | ccxt venue for the live path |

Note: Binance sometimes blocks cloud/datacenter IPs. The fetcher tries the
`data-api.binance.vision` mirror first (friendlier to cloud hosts) before
`api.binance.com`.
