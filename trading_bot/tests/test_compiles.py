"""Syntax-check every module (Streamlit pages can't be imported without streamlit)."""
from __future__ import annotations

import compileall
import os


def test_trading_bot_compiles():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assert compileall.compile_dir(root, quiet=1, force=True)
