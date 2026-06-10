"""CLI entrypoint. A run is launched bound to one (brand, role); there is no flag,
prompt, or tool that lets the agent change that binding mid-run.

    python -m src.cli --brand brand_b --role sales "Prep my pre-call briefing."
"""
from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv

from .agent import Agent
from .policy import Principal
from .store import LocalJsonAccountStore

VALID_ROLES = ("sales", "legal", "power_user")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Access Control Demonstrator (local).")
    parser.add_argument("--brand", required=True, help="Brand id, e.g. brand_b.")
    parser.add_argument("--role", required=True, choices=VALID_ROLES,
                        help="Access role bound for this run.")
    parser.add_argument("--effort", default="medium",
                        choices=("low", "medium", "high", "xhigh", "max"))
    parser.add_argument("query", nargs="?",
                        default="Prepare my pre-call briefing for this account.",
                        help="What to ask the agent.")
    args = parser.parse_args(argv)
    load_dotenv()  # picks up ANTHROPIC_API_KEY from the gitignored .env

    store = LocalJsonAccountStore()
    if args.brand not in store.list_brands():
        parser.error(f"unknown brand {args.brand!r}; known: {', '.join(store.list_brands())}")

    principal = Principal(brand=args.brand, role=args.role)
    from .tools import GovernedTools
    agent = Agent(principal, GovernedTools(store, principal), effort=args.effort)

    print(f"[run bound to brand={principal.brand} role={principal.role}]\n", file=sys.stderr)
    print(agent.run(args.query))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
