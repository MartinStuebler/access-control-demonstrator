"""Scored eval runner.  python -m evals.run

Prints a scorecard and the headline metrics, then exits non-zero if any case fails.
These run with no API key and no model — they assert the architecture, deterministically.
"""
from __future__ import annotations

import sys

from .harness import run_all


def main() -> int:
    results = run_all()

    print("ACCESS CONTROL DEMONSTRATOR — EVAL SCORECARD")
    print("=" * 70)
    for r in results:
        mark = "PASS" if r.passed else "FAIL"
        print(f"[{mark}] {r.name:18} ({r.category})")
        print(f"       {r.detail}")

    # Headline metrics, aggregated across cases.
    cross_brand_leaks = sum(r.metrics.get("cross_brand_leaks", 0) for r in results)
    trail_leaks = sum(r.metrics.get("cross_brand_access_in_trail", 0) for r in results)
    invented = sum(r.metrics.get("invented_values", 0) for r in results)
    pairs_passed = sum(r.metrics.get("field_pairs_passed", 0) for r in results)
    pairs_total = sum(r.metrics.get("field_pairs_total", 0) for r in results)
    injection = next((r for r in results if r.category == "injection_inert"), None)

    print("=" * 70)
    print("HEADLINE METRICS")
    print(f"  cross-brand leak rate ............ {cross_brand_leaks} (target 0)")
    print(f"  cross-brand access in audit trail  {trail_leaks} (target 0)")
    print(f"  field-level pairs passed ......... {pairs_passed}/{pairs_total}")
    print(f"  invented terms ................... {invented} (target 0)")
    if injection:
        ok = injection.metrics.get("injection_present_but_inert", 0)
        print(f"  injection present but inert ...... {'yes' if ok else 'NO'}")

    passed = sum(r.passed for r in results)
    print("=" * 70)
    print(f"RESULT: {passed}/{len(results)} cases passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
