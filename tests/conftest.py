"""Pytest configuration for slovetax-1 backend tests."""

import sys
from pathlib import Path

# Ensure project root is on sys.path when running tests from repo root.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
