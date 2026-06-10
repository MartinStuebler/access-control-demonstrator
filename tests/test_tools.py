"""Tool-layer enforcement, exercised offline (no Anthropic API calls).

These prove the tools enforce inside themselves — the data a role isn't entitled to
never appears in the tool's return value, so there is nothing for a model to leak.
"""
from __future__ import annotations

import pytest

from src.policy import Principal
from src.store import LocalJsonAccountStore
from src.tools import GovernedTools


@pytest.fixture
def store() -> LocalJsonAccountStore:
    return LocalJsonAccountStore()


def sales_a(store) -> GovernedTools:
    return GovernedTools(store, Principal(brand="brand_a", role="sales"))


# --- field-level enforcement inside get_contract_terms --------------------------

def test_sales_contract_terms_serve_operational_withhold_economic(store):
    out = sales_a(store).get_contract_terms()
    assert "minimum_order_quantity" in out["served"]      # operational → served
    assert "unit_price" not in out["served"]              # economic → not served
    withheld_fields = {w["field"] for w in out["withheld"]}
    assert {"unit_price", "exclusivity", "margin_floor"} <= withheld_fields


def test_economic_values_never_appear_in_sales_tool_output(store):
    # The raw price exists in the data; it must not be reachable through the tool.
    out = sales_a(store).get_contract_terms()
    blob = repr(out)
    assert "420" not in blob and "Noir Profond" not in blob  # no price, no exclusivity value


def test_legal_is_served_economic_fields(store):
    # Field boundary is real, not cosmetic: legal sees what sales cannot. (Legal runs
    # are exercised fully in Phase 3; this is the contrast proof.)
    legal = GovernedTools(store, Principal(brand="brand_a", role="legal"))
    out = legal.get_contract_terms()
    assert "EUR 420 per linear meter" == out["served"]["unit_price"]
    assert out["withheld"] == []


# --- draft_briefing: grounded, withheld-and-said-so -----------------------------

def test_sales_briefing_flags_withheld_and_leaks_no_values(store):
    out = sales_a(store).draft_briefing()
    text = out["briefing"]
    assert "withheld at your access level" in text
    assert "minimum order quantity" in text.lower()       # operational shown
    assert "420" not in text                               # economic value absent
    assert "unit_price" in [w["field"] for w in out["withheld"]]


# --- search_account_notes: scoped, returns injection as inert data --------------

def test_search_notes_scoped_and_substring(store):
    out = sales_a(store).search_account_notes("noir")
    assert out["brand"] == "brand_a"
    assert any("Noir Profond" in m["text"] for m in out["matches"])


def test_injection_note_is_returned_as_data_not_acted_on(store):
    # n3 is the planted injection. It comes back as a quotable note — that is correct;
    # the architecture makes it inert because Brand B data is unreachable regardless.
    out = sales_a(store).search_account_notes("atelier solene")
    assert any(m["id"] == "n3" for m in out["matches"])


# --- share_briefing is a non-sending stub ---------------------------------------

def test_share_briefing_pauses_and_does_not_send(store):
    out = sales_a(store).share_briefing("#partnerships")
    assert out["status"] == "pending_human_approval"
    assert out["destination"] == "#partnerships"


# --- the binding cannot be widened by the model ---------------------------------

def test_tools_only_ever_touch_the_bound_brand(store):
    # dispatch passes no brand/role from the model; every result is the bound brand.
    tools = sales_a(store)
    for name in ("get_account_overview", "get_contract_terms", "draft_briefing"):
        assert tools.dispatch(name, {})["brand"] == "brand_a"
