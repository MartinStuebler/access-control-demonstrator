"""Append-only, human-readable audit log (JSONL).

One sink, `audit/audit.jsonl`, that every run appends to. Each line is one event,
stamped with the run id and the bound (brand, role) scope. The audit log is the
demo's evidence: for a Brand-B run it shows every tool call scoped to brand_b and
nothing else, which is what proves no cross-brand access happened.

This maps 1:1 to the production design (PRD §9: an audit sink exported to a SIEM)
and to the Firebase upgrade (a Firestore `audit` collection, append-only via Cloud
Functions). The interface here is the seam the Firebase backend slots into.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .policy import CROSS_BRAND_BLOCK, Decision, Principal


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AuditLog:
    def __init__(self, principal: Principal, path: Path | None = None,
                 run_id: str | None = None, clock=_now_iso) -> None:
        self.principal = principal
        self.path = Path(path) if path else config.AUDIT_DIR / "audit.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id or f"{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"
        self._clock = clock

    def _write(self, event: str, **fields) -> None:
        record = {
            "ts": self._clock(),
            "run_id": self.run_id,
            "event": event,
            "brand": self.principal.brand,   # the scope this run is bound to
            "role": self.principal.role,
            **fields,
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    # --- run boundaries ----------------------------------------------------

    def run_start(self, query: str) -> None:
        self._write("run_start", query=query)

    def run_end(self, status: str) -> None:
        self._write("run_end", status=status)

    # --- per tool call -----------------------------------------------------

    def tool_call(self, tool: str, served: list, withheld: list) -> None:
        self._write("tool_call", tool=tool, served=served, withheld=withheld)

    def external_write_pending(self, tool: str, destination: str) -> None:
        # An external write paused for human approval — logged, not performed.
        self._write("external_write_pending", tool=tool, destination=destination)

    # --- enforcement events ------------------------------------------------

    def cross_brand_block(self, requested_brand: str, reason: str) -> None:
        self._write("cross_brand_block", requested_brand=requested_brand, reason=reason)

    def refusal(self, reason: str) -> None:
        self._write("refusal", reason=reason)

    def log_decision(self, requested_brand: str, decision: Decision) -> None:
        """Log a raw policy decision. Used by the operator cross-brand probe to put a
        real cross_brand_block line in the trail — the agent itself cannot trigger one
        because it has no way to name another brand."""
        if decision.code == CROSS_BRAND_BLOCK:
            self.cross_brand_block(requested_brand, decision.reason)
        else:
            self._write("decision", requested_brand=requested_brand,
                        code=decision.code, reason=decision.reason)
