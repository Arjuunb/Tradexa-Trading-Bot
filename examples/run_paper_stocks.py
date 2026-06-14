"""Run the strategy on Alpaca paper trading (US equities).

Requires:  pip install alpaca-py
Get free paper keys at https://alpaca.markets/.
"""
import logging
import os

from bot.brokers import get_broker
from bot.live import LiveRunner
from bot.risk import RiskConfig, RiskManager
from bot.strategies import SupportResistanceRejection


logging.basicConfig(level=logging.INFO)
SYMBOL = "SPY"

broker = get_broker(
    "alpaca",
    api_key=os.environ["ALPACA_KEY"],
    api_secret=os.environ["ALPACA_SECRET"],
    paper=True,
)

strategy = SupportResistanceRejection(SYMBOL, pivot=3, min_touches=2, rr_target=2.0)
risk = RiskManager(RiskConfig(risk_per_trade_pct=0.005, max_open_positions=2))

LiveRunner(broker, strategy, timeframe="1h", warmup_bars=200, risk=risk).run()
