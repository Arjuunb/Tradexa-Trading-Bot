"""Symbol universe + market prefs endpoints.

The multi-asset universe (crypto auto-synced from CCXT; stocks / ETFs / indices /
forex / commodities from the curated reference catalog), instant search, filters,
per-symbol market info, and persistent favorites / pins / watchlists.

Shared singletons resolve via ``_wa.<name>`` at request time (same pattern as the
other split routers).
"""
import webhook_api as _wa
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List

from services import symbol_universe as _su

router = APIRouter()


def _prefs() -> dict:
    return _wa.watchlist_store.get()


def _annotate(symbols: list[dict], prefs: Optional[dict] = None) -> list[dict]:
    """Tag each symbol with favorite / pinned flags for the UI."""
    prefs = prefs or _prefs()
    favs = {f.upper() for f in prefs.get("favorites", [])}
    pins = {p.upper() for p in prefs.get("pinned", [])}
    out = []
    for s in symbols:
        keys = {s["ticker"].upper(), s["symbol"].upper()}
        out.append({**s, "favorite": bool(keys & favs), "pinned": bool(keys & pins)})
    return out


# ─────────────────────────── universe ───────────────────────────
@router.get("/symbols/asset-classes")
def symbol_asset_classes():
    cat = _su.catalog()
    return {"asset_classes": _su.asset_classes(), "crypto_source": cat["crypto_source"],
            "synced_at": cat["synced_at"], "total": len(cat["symbols"])}


@router.get("/symbols/search")
def symbol_search(q: str = Query("", description="ticker or asset name"),
                  limit: int = Query(20, ge=1, le=50)):
    return {"query": q, "results": _annotate(_su.search(q, limit=limit))}


@router.get("/symbols")
def symbols_list(asset_class: str = "", quote: str = "", type: str = "",
                 favorites: bool = False, limit: int = Query(500, ge=1, le=2000)):
    prefs = _prefs()
    tickers = prefs.get("favorites") if favorites else None
    rows = _su.filter_symbols(asset_class=asset_class, quote=quote, type=type,
                              tickers=tickers, limit=limit)
    return {"count": len(rows), "symbols": _annotate(rows, prefs)}


@router.get("/symbols/info")
def symbol_info(symbol: str, timeframe: str = "1d"):
    info = _su.market_info(symbol, timeframe=timeframe)
    if not info.get("found"):
        raise HTTPException(404, f"Unknown symbol '{symbol}'")
    return {**info, **{k: _annotate([info])[0][k] for k in ("favorite", "pinned")}}


@router.post("/symbols/sync")
def symbols_sync(x_webhook_secret: Optional[str] = Header(default=None)):
    """Force a re-sync of the live crypto catalog from the exchange (CCXT)."""
    _wa._check_secret(x_webhook_secret)
    cat = _su.catalog(force=True)
    _wa.ledger.log(level="info", stage="market",
                   message=f"Symbol universe synced — {len(cat['symbols'])} symbols "
                           f"({cat['crypto_source']})")
    return {"synced": True, "total": len(cat["symbols"]),
            "crypto_source": cat["crypto_source"], "synced_at": cat["synced_at"]}


# ─────────────────────────── prefs: favorites / pins / watchlists ───────────────────────────
class FavoriteBody(BaseModel):
    symbol: str
    on: bool = True


class WatchlistCreate(BaseModel):
    name: str
    symbols: Optional[List[str]] = None


class WatchlistRename(BaseModel):
    id: str
    name: str


class WatchlistId(BaseModel):
    id: str


class WatchlistSymbol(BaseModel):
    id: str
    symbol: str
    on: bool = True


@router.get("/market/prefs")
def market_prefs():
    return _prefs()


@router.post("/market/favorite")
def market_favorite(body: FavoriteBody, x_webhook_secret: Optional[str] = Header(default=None)):
    _wa._check_secret(x_webhook_secret)
    return _wa.watchlist_store.set_favorite(body.symbol, body.on)


@router.post("/market/pin")
def market_pin(body: FavoriteBody, x_webhook_secret: Optional[str] = Header(default=None)):
    _wa._check_secret(x_webhook_secret)
    return _wa.watchlist_store.set_pin(body.symbol, body.on)


@router.post("/market/watchlist")
def market_watchlist_create(body: WatchlistCreate, x_webhook_secret: Optional[str] = Header(default=None)):
    _wa._check_secret(x_webhook_secret)
    if not (body.name or "").strip():
        raise HTTPException(400, "watchlist name is required")
    return _wa.watchlist_store.create_watchlist(body.name, body.symbols)


@router.post("/market/watchlist/rename")
def market_watchlist_rename(body: WatchlistRename, x_webhook_secret: Optional[str] = Header(default=None)):
    _wa._check_secret(x_webhook_secret)
    return _wa.watchlist_store.rename_watchlist(body.id, body.name)


@router.post("/market/watchlist/delete")
def market_watchlist_delete(body: WatchlistId, x_webhook_secret: Optional[str] = Header(default=None)):
    _wa._check_secret(x_webhook_secret)
    return _wa.watchlist_store.delete_watchlist(body.id)


@router.post("/market/watchlist/symbol")
def market_watchlist_symbol(body: WatchlistSymbol, x_webhook_secret: Optional[str] = Header(default=None)):
    _wa._check_secret(x_webhook_secret)
    return _wa.watchlist_store.set_watchlist_symbol(body.id, body.symbol, body.on)
