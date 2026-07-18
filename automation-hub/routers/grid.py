"""Server-side grid endpoints — start/stop/status a paper grid that keeps
trading with no browser open (see webhook_api.grid_start/grid_stop/grid_status).
Live trading stays locked; the grid is paper only."""
import webhook_api as _wa
from fastapi import APIRouter, Header, HTTPException, Body  # noqa: F401
from typing import Optional  # noqa: F401

router = APIRouter()


@router.post("/grid/start")
def grid_start(cfg: dict = Body(...),
               x_webhook_secret: _wa.Optional[str] = _wa.Header(default=None)):
    """Start a server-side paper grid from a config
    {symbol, timeframe, lower, upper, levels, geometric, investment, leverage, fee_pct}.
    Reconfigures/replaces any existing grid. Persisted so it survives a restart."""
    _wa._check_secret(x_webhook_secret)
    return _wa.grid_start(cfg or {})


@router.post("/grid/stop")
def grid_stop(x_webhook_secret: _wa.Optional[str] = _wa.Header(default=None)):
    """Stop the server grid and clear its persisted state."""
    _wa._check_secret(x_webhook_secret)
    return _wa.grid_stop()


@router.get("/grid/status")
def grid_status():
    """Current server-grid state (running, realized/unrealized, fills, feed)."""
    return _wa.grid_status()
