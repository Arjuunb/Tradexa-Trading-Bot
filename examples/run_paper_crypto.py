"""Run the strategy live on Binance testnet (paper trading) via ccxt.

Requires:  pip install ccxt
Set BINANCE_TESTNET_KEY / BINANCE_TESTNET_SECRET as env vars.
"""
import logging
import os

from bot.brokers import get_broker
from bot.live import LiveRunner
from bot.risk import RiskConfig, RiskManager
from bot.strategies import SupportResistanceRejection


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

SYMBOL = "BTC/USDT"

broker = get_broker(
    "ccxt",
    exchange_id="binance",
    api_key=os.environ.get("BINANCE_TESTNET_KEY"),
    api_secret=os.environ.get("BINANCE_TESTNET_SECRET"),
    sandbox=True,
)

strategy = SupportResistanceRejection(SYMBOL, pivot=3, min_touches=2, rr_target=2.0)
risk = RiskManager(RiskConfig(risk_per_trade_pct=0.005, max_open_positions=1))

LiveRunner(broker, strategy, timeframe="1h", warmup_bars=300, risk=risk, dry_run=False).run()
