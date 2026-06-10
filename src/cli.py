"""CLI entrypoint. A run is launched bound to one (brand, role); there is no flag,
prompt, or tool that lets the agent change that binding mid-run.

    python -m src.cli --brand brand_b --role sales "Prep my pre-call briefing."
"""
from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv

from .agent import Agent
from .audit import AuditLog
from .policy import Principal, decide
from .store import LocalJsonAccountStore

VALID_ROLES = ("sales", "legal", "power_user")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Access Control Demonstrator (local).")
    parser.add_argument("--brand", required=True, help="Brand id, e.g. brand_b.")
    parser.add_argument("--role", required=True, choices=VALID_ROLES,
                        help="Access role bound for this run.")
    parser.add_argument("--effort", default="medium",
                        choices=("low", "medium", "high", "xhigh", "max"))
    parser.add_argument("--cross-brand-probe", metavar="BRAND", default=None,
                        help="Operator/eval affordance: feed a BRAND request straight "
                             "to the policy engine and log the cross_brand_block. The "
                             "agent itself cannot do this — it has no way to name a brand.")
    parser.add_argument("query", nargs="?",
                        default="Prepare my pre-call briefing for this account.",
                        help="What to ask the agent.")
    args = parser.parse_args(argv)
    load_dotenv()  # picks up ANTHROPIC_API_KEY from the gitignored .env

    store = LocalJsonAccountStore()
    if args.brand not in store.list_brands():
        parser.error(f"unknown brand {args.brand!r}; known: {', '.join(store.list_brands())}")

    principal = Principal(brand=args.brand, role=args.role)
    audit = AuditLog(principal)
    # The trusted launcher resolves the brand's display label as binding metadata and
    # hands it to the Agent, so the Agent itself never reads the store.
    brand_name = store.get_account(args.brand).get("brand_name", args.brand)
    from .tools import GovernedTools
    agent = Agent(principal, GovernedTools(store, principal, audit=audit),
                  effort=args.effort, audit=audit, brand_name=brand_name)

    print(f"[run {audit.run_id} bound to brand={principal.brand} role={principal.role}]",
          file=sys.stderr)
    print(agent.run(args.query))

    # Operator probe: prove the policy engine blocks + logs a cross-brand request.
    if args.cross_brand_probe:
        d = decide(principal, args.cross_brand_probe, "public", store.get_entitlements())
        audit.log_decision(args.cross_brand_probe, d)
        print(f"\n[cross-brand probe] requested {args.cross_brand_probe}: "
              f"{d.code} — {d.reason}", file=sys.stderr)

    print(f"[audit: {audit.path} | run_id={audit.run_id}]", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
