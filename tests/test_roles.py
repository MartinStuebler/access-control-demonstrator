"""Phase 3: the legal comparison and the power-user run, with field-grain audit.

Sales withholds economic; legal (comparison) is served it; power_user is served all
fields of its bound brand — and is STILL refused another brand, with the audit trail
showing it scoped to exactly one brand.
"""
from __future__ import annotations

import json

import pytest

from src import policy
from src.audit import AuditLog
from src.policy import Principal, decide
from src.store import LocalJsonAccountStore
from src.tools import GovernedTools

ECONOMIC = ("unit_price", "price_escalator", "exclusivity", "margin_floor")


@pytest.fixture
def store() -> LocalJsonAccountStore:
    return LocalJsonAccountStore()


def read_events(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def fixed_audit(principal, tmp_path):
    return AuditLog(principal, path=tmp_path / "audit.jsonl",
                    run_id="run-test", clock=lambda: "2026-06-10T00:00:00+00:00")


# --- Act 2: legal is the comparison that proves the field boundary is real ------

def test_legal_served_every_economic_field_sales_is_not(store):
    legal = GovernedTools(store, Principal("brand_b", "legal")).get_contract_terms()
    sales = GovernedTools(store, Principal("brand_b", "sales")).get_contract_terms()
    for field in ECONOMIC:
        assert field in legal["served"]            # legal sees it
        assert field not in sales["served"]        # sales does not
        assert field in {w["field"] for w in sales["withheld"]}
    assert legal["withheld"] == []


# --- Act 3: power_user — full fields of the bound brand, no other brand ----------

def test_power_user_served_all_fields_no_withheld(store):
    out = GovernedTools(store, Principal("brand_b", "power_user")).get_contract_terms()
    assert out["withheld"] == []
    for field in ECONOMIC:
        assert field in out["served"]


def test_power_user_briefing_includes_economic_no_withheld_line(store):
    out = GovernedTools(store, Principal("brand_b", "power_user")).draft_briefing()
    assert "withheld at your access level" not in out["briefing"]
    assert "unit price" in out["briefing"].lower()


def test_power_user_still_refused_other_brand(store):
    # Privilege does not buy cross-brand reach: the bound brand is the only brand.
    d = decide(Principal("brand_b", "power_user"), "brand_a", "economic",
               store.get_entitlements())
    assert d.code == policy.CROSS_BRAND_BLOCK


def test_power_user_audit_scoped_to_one_brand(store, tmp_path):
    """The required power-user evidence: full fields served, other brand never touched."""
    p = Principal("brand_b", "power_user")
    log = fixed_audit(p, tmp_path)
    tools = GovernedTools(store, p, audit=log)

    log.run_start("Full brief for Atelier Solene.")
    tools.dispatch("draft_briefing", {})
    # Operator probes Brand A to show the engine refuses even a power_user.
    log.log_decision("brand_a", decide(p, "brand_a", "public", store.get_entitlements()))
    log.run_end("completed")

    events = read_events(log.path)
    tool_calls = [e for e in events if e["event"] == "tool_call"]

    # Every served-data event is scoped to the one bound brand — never brand_a.
    assert all(e["brand"] == "brand_b" for e in tool_calls)
    assert not any(e["brand"] == "brand_a" for e in tool_calls)

    # Full fields served, nothing withheld for the power_user.
    (brief,) = [e for e in tool_calls if e["tool"] == "draft_briefing"]
    assert brief["withheld"] == []
    for field in ECONOMIC:
        assert field in brief["served"]

    # The only mention of brand_a is the operator-initiated, refused probe.
    (block,) = [e for e in events if e["event"] == "cross_brand_block"]
    assert block["requested_brand"] == "brand_a"
    assert block["initiated_by"] == "operator_probe"
