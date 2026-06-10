"""The store is a dumb data source: it loads the real files and does NOT filter."""
from __future__ import annotations

import pytest

from src.store import LocalJsonAccountStore


@pytest.fixture
def store() -> LocalJsonAccountStore:
    return LocalJsonAccountStore()


def test_lists_all_three_brands(store):
    assert store.list_brands() == ["brand_a", "brand_b", "brand_c"]


def test_get_account_returns_matching_brand(store):
    acct = store.get_account("brand_a")
    assert acct["brand_id"] == "brand_a"
    assert acct["brand_name"] == "Maison Lirelle"


def test_unknown_brand_raises(store):
    with pytest.raises(KeyError):
        store.get_account("brand_z")


def test_store_does_not_filter_economic_fields(store):
    # The store must hand back raw economic fields untouched. Filtering is policy's
    # job, not the store's — proven by the sensitive unit_price being present here.
    terms = store.get_account("brand_a")["contract_terms"]
    assert terms["unit_price"]["visibility"] == "economic"
    assert "420" in terms["unit_price"]["value"]


def test_entitlements_load(store):
    ent = store.get_entitlements()
    assert ent["roles"]["sales"]["can_see"] == ["public", "operational"]
    assert "economic" in ent["roles"]["legal"]["can_see"]
