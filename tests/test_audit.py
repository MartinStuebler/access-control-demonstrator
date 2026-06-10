"""Audit log: events are written append-only, scoped to the bound (brand, role),
and the cross-brand block is logged when the policy engine refuses one."""
from __future__ import annotations

import json

import pytest

from src import policy
from src.audit import AuditLog
from src.policy import Principal, decide
from src.store import LocalJsonAccountStore
from src.tools import GovernedTools


@pytest.fixture
def store() -> LocalJsonAccountStore:
    return LocalJsonAccountStore()


def read_events(path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def fixed_audit(principal, tmp_path) -> AuditLog:
    # Deterministic clock + run_id so assertions are stable.
    return AuditLog(principal, path=tmp_path / "audit.jsonl",
                    run_id="run-test", clock=lambda: "2026-06-10T00:00:00+00:00")


def test_every_event_carries_run_id_and_scope(tmp_path):
    p = Principal(brand="brand_b", role="sales")
    log = fixed_audit(p, tmp_path)
    log.run_start("prep brief")
    log.run_end("completed")
    events = read_events(log.path)
    assert [e["event"] for e in events] == ["run_start", "run_end"]
    for e in events:
        assert e["run_id"] == "run-test"
        assert e["brand"] == "brand_b" and e["role"] == "sales"
        assert e["ts"] == "2026-06-10T00:00:00+00:00"


def test_tool_call_logs_served_and_withheld(store, tmp_path):
    p = Principal(brand="brand_a", role="sales")
    log = fixed_audit(p, tmp_path)
    tools = GovernedTools(store, p, audit=log)
    tools.dispatch("get_contract_terms", {})
    (event,) = read_events(log.path)
    assert event["event"] == "tool_call"
    assert event["tool"] == "get_contract_terms"
    assert "minimum_order_quantity" in event["served"]
    withheld_fields = {w["field"] for w in event["withheld"]}
    assert "unit_price" in withheld_fields
    # The withheld value itself is never in the log — only the field name + reason.
    assert "420" not in json.dumps(event)


def test_share_briefing_logs_external_write_pending(store, tmp_path):
    p = Principal(brand="brand_a", role="sales")
    log = fixed_audit(p, tmp_path)
    GovernedTools(store, p, audit=log).dispatch("share_briefing", {"channel": "#partners"})
    (event,) = read_events(log.path)
    assert event["event"] == "external_write_pending"
    assert event["destination"] == "#partners"


def test_cross_brand_request_is_logged_as_block(store, tmp_path):
    # The operator probe path: a Brand-A request from a Brand-B run is blocked + logged.
    p = Principal(brand="brand_b", role="sales")
    log = fixed_audit(p, tmp_path)
    d = decide(p, "brand_a", "public", store.get_entitlements())
    log.log_decision("brand_a", d)
    (event,) = read_events(log.path)
    assert event["event"] == "cross_brand_block"
    assert event["requested_brand"] == "brand_a"
    # The trail must read "operator probed, policy refused" — not "agent tried".
    assert event["initiated_by"] == "operator_probe"
    assert d.code == policy.CROSS_BRAND_BLOCK


def test_audit_is_append_only(store, tmp_path):
    p = Principal(brand="brand_c", role="power_user")
    log = fixed_audit(p, tmp_path)
    log.run_start("a")
    log.tool_call("get_account_overview", ["profile"], [])
    log.run_end("completed")
    assert len(read_events(log.path)) == 3  # nothing overwritten
