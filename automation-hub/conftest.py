"""Make the Hub's sibling packages importable during test collection."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
