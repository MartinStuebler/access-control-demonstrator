"""The enforcement matrix, proven against the real entitlements and real data tags.

These tests are the field-grain evidence in unit form: they assert the exact
served/withheld decisions the demo and evals depend on, before any agent exists.
"""
from __future__ import annotations

import pytest

from src import policy
from src.policy import Principal, decide
from src.store import LocalJsonAccountStore


@pytest.fixture
def ent() -> dict:
    return LocalJsonAccountStore().get_entitlements()


@pytest.fixture
def store() -> LocalJsonAccountStore:
    return LocalJsonAccountStore()


# --- Axis 2: field/section visibility -------------------------------------------

def test_sales_sees_public_and_operational(ent):
    p = Principal(brand="brand_a", role="sales")
    assert decide(p, "brand_a", "public", ent).code == policy.SERVED
    assert decide(p, "brand_a", "operational", ent).code == policy.SERVED


def test_sales_withholds_economic(ent):
    p = Principal(brand="brand_a", role="sales")
    d = decide(p, "brand_a", "economic", ent)
    assert not d.allowed
    assert d.code == policy.WITHHELD


def test_legal_sees_economic(ent):
    p = Principal(brand="brand_a", role="legal")
    assert decide(p, "brand_a", "economic", ent).code == policy.SERVED


def test_power_user_sees_economic(ent):
    p = Principal(brand="brand_b", role="power_user")
    assert decide(p, "brand_b", "economic", ent).code == policy.SERVED


# --- Axis 1: brand tenancy ------------------------------------------------------

def test_cross_brand_blocked_for_sales(ent):
    # Bound to B, asks for A: refused even for public data.
    p = Principal(brand="brand_b", role="sales")
    d = decide(p, "brand_a", "public", ent)
    assert not d.allowed
    assert d.code == policy.CROSS_BRAND_BLOCK


def test_cross_brand_blocked_even_for_power_user(ent):
    # The privileged role is still tenancy-scoped per run: no cross-brand reach.
    p = Principal(brand="brand_b", role="power_user")
    d = decide(p, "brand_a", "economic", ent)
    assert not d.allowed
    assert d.code == policy.CROSS_BRAND_BLOCK


# --- Fail-closed behaviour -------------------------------------------------------

def test_unknown_role_denied(ent):
    p = Principal(brand="brand_a", role="ceo")
    assert decide(p, "brand_a", "public", ent).code == policy.DENIED_UNKNOWN_ROLE


def test_unknown_visibility_value_denied(ent):
    # A typo'd tag value in the data must never default to served.
    p = Principal(brand="brand_a", role="power_user")
    assert decide(p, "brand_a", "top_secret", ent).code == policy.DENIED_UNKNOWN_VISIBILITY


def test_absent_visibility_tag_denied(ent):
    # A field with NO visibility key at all. The tool extracts it with .get(), so an
    # absent tag arrives as None, and the same gate must fail closed (not serve, not
    # crash). This is distinct from a bad value: it's the key being missing entirely.
    p = Principal(brand="brand_a", role="power_user")  # the most privileged role
    field_missing_tag = {"value": "EUR 999 per linear meter"}  # no "visibility" key
    visibility = field_missing_tag.get("visibility")  # -> None
    d = decide(p, "brand_a", visibility, ent)
    assert not d.allowed
    assert d.code == policy.DENIED_UNKNOWN_VISIBILITY


# --- Data-driven, not hardcoded: the cases a static field list would get wrong ---

def test_enforcement_follows_the_tag_not_the_field_name(ent, store):
    """Run every contract field of every brand through the real tag + the policy.

    This proves the enforcer obeys each field's own visibility tag:
      - Brand C 'exclusivity' is tagged operational -> sales IS served it.
      - Brand A 'exclusivity' is tagged economic    -> sales is withheld.
      - Brand C 'volume_rebate' is tagged economic  -> sales is withheld.
    A hardcoded "withhold pricing/margin/exclusivity" list would fail all three.
    """
    sales_c = Principal(brand="brand_c", role="sales")
    terms_c = store.get_account("brand_c")["contract_terms"]
    assert decide(sales_c, "brand_c", terms_c["exclusivity"]["visibility"], ent).code == policy.SERVED
    assert decide(sales_c, "brand_c", terms_c["volume_rebate"]["visibility"], ent).code == policy.WITHHELD

    sales_a = Principal(brand="brand_a", role="sales")
    terms_a = store.get_account("brand_a")["contract_terms"]
    assert decide(sales_a, "brand_a", terms_a["exclusivity"]["visibility"], ent).code == policy.WITHHELD

    # And legal sees all economic terms of its bound brand.
    legal_a = Principal(brand="brand_a", role="legal")
    for field in terms_a.values():
        assert decide(legal_a, "brand_a", field["visibility"], ent).allowed
