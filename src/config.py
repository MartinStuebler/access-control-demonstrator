"""Paths and fixed constants.

The demo data is a read-only input committed before any code. We do NOT reshape it
to a tidier layout; the loader points at where it actually lives. Code conforms to
the data, never the reverse.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# The synthetic accounts (brand_*.json + entitlements.json) and the legalese PDFs.
# These directory names have spaces and are deliberately left as-authored.
ACCOUNTS_DIR = REPO_ROOT / "Demo data" / "synth intelligence files"
CONTRACTS_DIR = REPO_ROOT / "Demo data" / "full contract synth files"

AUDIT_DIR = REPO_ROOT / "audit"

# The closed set of visibility tags. Anything outside this set is treated as a
# data error and fails closed (never served), so a typo in the data cannot leak.
VISIBILITY_LEVELS = frozenset({"public", "operational", "economic"})
