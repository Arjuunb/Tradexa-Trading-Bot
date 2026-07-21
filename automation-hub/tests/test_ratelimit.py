"""Phase A hardening: the sliding-window rate limiter + its wiring."""
from services.ratelimit import RateLimiter


def test_sliding_window_allows_then_blocks():
    rl = RateLimiter()
    # 3 per 10s window, deterministic clock
    for t in (0, 1, 2):
        assert rl.allow("k", 3, 10, now=t)          # first 3 within the window
    assert not rl.allow("k", 3, 10, now=3)          # 4th within window -> blocked (not recorded)
    assert not rl.allow("k", 3, 10, now=9)          # still full (0,1,2 in window)
    assert rl.allow("k", 3, 10, now=13)             # >10s past hit@2 -> 0,1,2 aged out


def test_keys_are_independent():
    rl = RateLimiter()
    assert rl.allow("a", 1, 10, now=0)
    assert not rl.allow("a", 1, 10, now=0)
    assert rl.allow("b", 1, 10, now=0)              # different key, own budget


def test_retry_after_and_reset():
    rl = RateLimiter()
    rl.allow("k", 1, 30, now=100)
    assert not rl.allow("k", 1, 30, now=105)
    assert rl.retry_after("k", 30, now=105) == 26   # oldest hit@100 frees at 130
    rl.reset("k")
    assert rl.allow("k", 1, 30, now=106)            # cleared
