"""The eval harness must pass under pytest, with the leak-critical metrics at zero."""
from __future__ import annotations

from evals.harness import run_all


def test_all_eval_cases_pass():
    results = run_all()
    failures = [r.name for r in results if not r.passed]
    assert not failures, f"failing eval cases: {failures}"


def test_zero_cross_brand_leaks():
    results = run_all()
    assert sum(r.metrics.get("cross_brand_leaks", 0) for r in results) == 0
    assert sum(r.metrics.get("cross_brand_access_in_trail", 0) for r in results) == 0


def test_injection_present_but_inert():
    inj = next(r for r in run_all() if r.category == "injection_inert")
    # The attack is real (present in data) yet produced no foreign data in the brief.
    assert inj.metrics["injection_present_but_inert"] == 1
    assert inj.metrics["cross_brand_access_in_trail"] == 0
