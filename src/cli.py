"""CLI entrypoint. A run is launched bound to one (brand, role); there is no flag,
prompt, or tool that lets the agent change that binding mid-run.

    python -m src.cli --brand brand_b --role sales "Prep my pre-call briefing."

Two backends, one agent. `--backend local` (default) reads the synthetic JSON through
the Day 1 tools — the offline baseline. `--backend firebase` swaps the substrate: the
agent's read tools become Cloud Functions on the emulator that verify the signed token
and read only entitled Firestore tiers. The agent and its enforcement contract are
unchanged; only where the data lives and what enforces access moves.
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
    parser.add_argument("--backend", default="local", choices=("local", "firebase"),
                        help="local (default): Day 1 JSON tools. firebase: Cloud Functions "
                             "on the emulator verify the token and read entitled tiers.")
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

    principal = Principal(brand=args.brand, role=args.role)

    if args.backend == "firebase":
        return _run_firebase(args, principal)

    store = LocalJsonAccountStore()
    if args.brand not in store.list_brands():
        parser.error(f"unknown brand {args.brand!r}; known: {', '.join(store.list_brands())}")

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


def _run_firebase(args, principal: Principal) -> int:
    """Firebase mode: the agent's tools are Cloud Functions on the emulator. Identity is
    a signed ID token, not a config value; the Functions verify it and read only entitled
    tiers. The Agent class itself is unchanged — it just gets a different tools object,
    and still holds no direct data source. (Audit-to-Firestore is F5; this phase runs
    without the local audit sink to keep the two concerns separate.)"""
    from .fb_backend import FunctionsTools, FirebaseFunctionError, ACCOUNT_EMAILS
    if (args.brand, args.role) not in ACCOUNT_EMAILS:
        seeded = ", ".join(f"{b}/{r}" for (b, r) in ACCOUNT_EMAILS)
        print(f"no seeded Firebase identity for {args.brand}/{args.role}; "
              f"seeded: {seeded}", file=sys.stderr)
        return 2
    try:
        tools = FunctionsTools(args.brand, args.role)
        brand_name = tools.brand_label()
    except FirebaseFunctionError as e:
        print(f"[firebase] could not start — is the emulator running "
              f"(cd firebase && npm run emulators)?  detail: {e}", file=sys.stderr)
        return 1

    agent = Agent(principal, tools, effort=args.effort, audit=None, brand_name=brand_name)
    print(f"[firebase run bound to brand={principal.brand} role={principal.role} "
          f"as {tools.email}; tools are Cloud Functions]", file=sys.stderr)
    print(agent.run(args.query))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
