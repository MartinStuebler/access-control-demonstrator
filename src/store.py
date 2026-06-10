"""Storage interface.

One abstract `AccountStore` with a single local backend. The store is a *dumb data
source*: it returns raw, unfiltered brand records and knows nothing about roles or
entitlements. All access-control filtering happens above it, in policy.py, so there
is exactly one enforcement point.

This separation is what lets a Firebase backend (PRD Section 17) slot in later: it
implements the same three methods, and the enforcement logic does not move.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path

from . import config


class AccountStore(ABC):
    """A source of raw brand records and the entitlements config. No filtering."""

    @abstractmethod
    def list_brands(self) -> list[str]:
        """All known brand ids, e.g. ['brand_a', 'brand_b', 'brand_c']."""

    @abstractmethod
    def get_account(self, brand: str) -> dict:
        """Raw, UNFILTERED record for one brand. Filtering is policy.py's job."""

    @abstractmethod
    def get_entitlements(self) -> dict:
        """The role -> can_see config (entitlements.json), verbatim."""


class LocalJsonAccountStore(AccountStore):
    """Reads the synthetic JSON files. Backend used for the local prototype."""

    def __init__(self, accounts_dir: Path | None = None) -> None:
        self._dir = Path(accounts_dir) if accounts_dir else config.ACCOUNTS_DIR
        if not self._dir.is_dir():
            raise FileNotFoundError(f"accounts dir not found: {self._dir}")
        # Read-only inputs, so caching the parsed JSON for the run is safe.
        self._accounts: dict[str, dict] = {}
        self._entitlements: dict | None = None

    def list_brands(self) -> list[str]:
        # Brand id == file stem, e.g. brand_a.json -> "brand_a".
        stems = (p.stem for p in self._dir.glob("brand_*.json"))
        return sorted(stems)

    def get_account(self, brand: str) -> dict:
        if brand not in self._accounts:
            path = self._dir / f"{brand}.json"
            if not path.is_file():
                raise KeyError(f"unknown brand: {brand!r}")
            self._accounts[brand] = json.loads(path.read_text(encoding="utf-8"))
        return self._accounts[brand]

    def get_entitlements(self) -> dict:
        if self._entitlements is None:
            path = self._dir / "entitlements.json"
            if not path.is_file():
                raise FileNotFoundError(f"entitlements.json not found in {self._dir}")
            self._entitlements = json.loads(path.read_text(encoding="utf-8"))
        return self._entitlements
