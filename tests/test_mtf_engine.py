

def test_trends_from_stream_resamples_higher_tfs():
    from services.mtf_engine import trends_from_stream
    # 15m exec stream -> should derive 4H / Daily / Weekly (Weekly likely n/a)
    bars = _up(n=700)
    t = trends_from_stream(bars, "15m")
    assert "4H" in t and "Daily" in t and "Weekly" in t
    assert t["4H"] in ("Bullish", "Bearish", "Neutral", "n/a")
    # a clean uptrend resampled to 4H should read bullish
    assert t["4H"] == "Bullish"
    # exec >= a timeframe is excluded (4h exec has no 4H key)
    assert "4H" not in trends_from_stream(bars, "4h")


def test_adapter_blocks_counter_higher_timeframe():
    from strategies.custom_adapter import CustomStrategyAdapter
    # long strategy fed a clean DOWNtrend -> higher timeframes bearish -> blocked
    spec = {"name": "X", "symbol": "BTCUSDT", "timeframe": "15m", "side": "long",
            "entry": {"op": "AND", "rules": [{"type": "rsi", "op": "below", "value": 100}]},
            "stop": {"type": "atr", "mult": 1.5, "period": 14},
            "target": {"type": "rr", "rr": 2.0}, "quality_filter": False, "mtf_filter": True}
    blocks = []
    ad = CustomStrategyAdapter("BTCUSDT", spec, on_block=blocks.append)
    sig = None
    for b in _down(n=400):
        sig = ad.on_bar(b) or sig
    # with the higher timeframes bearish, no long signal should survive the gate
    assert sig is None
    assert blocks and any("oppose" in b["reason"] or "conflict" in b["reason"].lower() for b in blocks)


def test_adapter_mtf_can_be_disabled():
    from strategies.custom_adapter import CustomStrategyAdapter
    spec = {"name": "X", "symbol": "BTCUSDT", "timeframe": "15m", "side": "long",
            "entry": {"op": "AND", "rules": [{"type": "rsi", "op": "below", "value": 100}]},
            "stop": {"type": "atr", "mult": 1.5, "period": 14},
            "target": {"type": "rr", "rr": 2.0}, "quality_filter": False, "mtf_filter": False}
    ad = CustomStrategyAdapter("BTCUSDT", spec)
    assert ad._mtf_filter is False
