# Multi-asset symbol universe

Expands the tradable universe from a small crypto list to a searchable,
multi-asset catalog with favorites and watchlists.

## Asset classes

| Class | Symbol source | Live quotes |
|-------|---------------|-------------|
| **Crypto** | **Auto-synced from CCXT** (`load_markets` on `HUB_EXCHANGE`, default Binance) — spot + perps, tracks whatever the exchange lists | CCXT cached candle feed |
| Stocks (NASDAQ / NYSE / LSE) | Curated reference catalog | **Yahoo Finance** (no key) |
| ETFs | Curated reference catalog | **Yahoo Finance** (no key) |
| Indices (S&P 500, NASDAQ 100, Dow, FTSE 100, DAX, Nikkei 225…) | Curated reference catalog | **Yahoo Finance** (no key) |
| Forex (EUR/USD, GBP/USD…) | Curated reference catalog | **Yahoo Finance** (no key) |
| Commodities (Gold, Silver, WTI, Brent, Nat Gas…) | Curated reference catalog | **Yahoo Finance** (no key) |

**No fabricated data.** Crypto pairs are synced live from the exchange and never
hardcoded — new listings appear and delistings drop on the next sync. When the
exchange is unreachable crypto falls back to a curated seed list so the universe
is never empty. Non-crypto quotes come from **Yahoo Finance with no API key**
(`services/quote_provider.py`, reusing the endpoint the news module already
calls); each symbol is mapped to its Yahoo ticker (LSE → `.L`, indices → `^GSPC`
etc., forex → `EURUSD=X`, commodities → `GC=F` etc.). If Yahoo is unreachable
(offline / a blocked cloud IP) the price is reported as **unavailable**, never
invented.

## Backend

- `data/symbol_catalog.json` — the curated reference catalog + crypto seed list
  + crypto name map.
- `services/symbol_universe.py` — builds the merged universe (`catalog`, cached
  1h), `search` (ticker **or** asset name, ranked for autocomplete),
  `filter_symbols` (asset class / quote / type / favorites), `asset_classes`,
  `market_status` (exchange-session aware, UTC), and `market_info` (price /
  24h change / volume / status / exchange / type / session — real for crypto).
- `data/watchlist_store.py` — persistent favorites, pins and watchlists (a tiny
  SQLite JSON store under `HUB_DATA_DIR`, like the paper account) — survives
  logout / restart.
- `routers/symbols.py` — endpoints:
  - `GET /symbols/asset-classes` · `GET /symbols/search?q=` ·
    `GET /symbols?asset_class=&quote=&type=&favorites=` · `GET /symbols/info?symbol=`
  - `POST /symbols/sync` — force a live CCXT re-sync
  - `GET /market/prefs` · `POST /market/favorite` · `POST /market/pin`
  - `POST /market/watchlist` (create) · `/rename` · `/delete` · `/symbol` (add/remove)

## Frontend

A new **Symbol Explorer** page (`pages/SymbolExplorer.tsx`, nav item "Symbols"):
professional search bar with instant autocomplete (ticker or name), asset-class
tabs with counts, crypto quote/type filters (USDT / BTC · Spot / Futures), a
Favorites tab, user watchlists, star-to-favorite and pin actions, and a Market
Info panel (price, 24h change, 24h volume, market status, exchange, asset type,
trading session).

## Tests

`tests/test_symbol_universe.py` (19): catalog spans all six classes, offline
fallback, search by ticker/name, quote/class/type filters, market status
(crypto 24/7, equities closed on weekends / open mid-session), honest metadata
with no fabricated stock price, and favorites / pins / watchlist CRUD +
persistence. Full backend suite: 780 passed.
