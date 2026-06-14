"""Entry point so ``python -m bot ...`` works.

The actual argument parsing lives in :mod:`bot.cli` so it can be imported
and called from tests without re-entering this module.
"""
from __future__ import annotations

import sys

from bot.cli import main


if __name__ == "__main__":
    sys.exit(main())
