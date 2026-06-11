"""Firebase-mode tool surface (F4).

The Day 1 agent reaches data through Python methods that filter in-process. In Firebase
mode it reaches data ONLY through Cloud Functions: this module signs in to the Auth
emulator as the bound account, gets a signed ID token, and calls the callable Functions
with that token. The agent holds no Firestore client — identity rides on the token, the
Function verifies it server-side and reads only entitled tiers, and the F3 rules sit
underneath. brand/role are never sent in the call; they live in the signed token.

Emulator-only by construction: the hosts below are local emulator ports, and the
sign-in uses the throwaway demo password. Nothing here can touch a real project.
"""
from __future__ import annotations

import json
import sys
import urllib.request
import urllib.error

from .tools import compose_briefing

# Local emulator endpoints (see firebase/firebase.json). The Auth emulator ignores the
# API key value; any non-empty string is accepted.
AUTH_BASE = "http://127.0.0.1:9099/identitytoolkit.googleapis.com/v1"
FUNCTIONS_BASE = "http://127.0.0.1:5001/demo-access-control/us-central1"
SHARED_PASSWORD = "demo-password"  # emulator-only, documented in firebase/README.md

# (brand, role) -> seeded email. Mirrors firebase/seed/accounts.js, the single source of
# truth for the six identities. brand_c has no seeded identity (it exists only to prove
# rule symmetry), so no agent run binds to it.
ACCOUNT_EMAILS = {
    ("brand_a", "sales"): "sales@lirelle.demo",
    ("brand_a", "legal"): "legal@lirelle.demo",
    ("brand_a", "power_user"): "power@lirelle.demo",
    ("brand_b", "sales"): "sales@solene.demo",
    ("brand_b", "legal"): "legal@solene.demo",
    ("brand_b", "power_user"): "power@solene.demo",
}


class FirebaseFunctionError(RuntimeError):
    """A callable Function refused the call (e.g. unauthenticated / permission-denied)."""

    def __init__(self, status: str, message: str) -> None:
        super().__init__(f"{status}: {message}")
        self.status = status
        self.message = message


def _post(url: str, body: dict, headers: dict | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def sign_in(email: str, password: str = SHARED_PASSWORD) -> str:
    """Sign in to the Auth emulator and return the signed ID token (with custom claims)."""
    status, body = _post(
        f"{AUTH_BASE}/accounts:signInWithPassword?key=demo",
        {"email": email, "password": password, "returnSecureToken": True},
    )
    if status != 200 or "idToken" not in body:
        raise FirebaseFunctionError("sign_in_failed", json.dumps(body))
    return body["idToken"]


def call_function(name: str, id_token: str, data: dict | None = None) -> dict:
    """Call a callable Function with the Bearer token; return its `result` or raise."""
    status, body = _post(
        f"{FUNCTIONS_BASE}/{name}",
        {"data": data or {}},
        {"Authorization": f"Bearer {id_token}"},
    )
    if "error" in body:
        err = body["error"]
        raise FirebaseFunctionError(err.get("status", str(status)), err.get("message", ""))
    return body.get("result", {})


class FirestoreAuditSink:
    """The firebase-mode audit sink: each record is appended to the Firestore `audit`
    collection through the Admin-path `log_audit` Function (verified token, server-stamped
    identity, append-only). A client cannot write `audit` directly — the F3 rules deny it —
    so this Function is the only path. Holds the run's signed token; identity on the stored
    line is re-derived server-side from that token, never from the record we send.

    Warn-but-don't-abort: an audit write failure prints a loud `[audit] WARN` to stderr (an
    evidence failure is never swallowed) but does not crash the brief — the run still
    completes and the operator sees the gap."""

    def __init__(self, id_token: str) -> None:
        self._id_token = id_token

    def __call__(self, record: dict) -> None:
        try:
            call_function("log_audit", self._id_token, {"record": record})
        except FirebaseFunctionError as e:
            print(f"[audit] WARN: event {record.get('event')!r} not written to Firestore "
                  f"audit ({e.status}: {e.message})", file=sys.stderr)


class FunctionsTools:
    """Firebase-mode replacement for GovernedTools. Same dispatch() surface; every read
    goes through a Cloud Function that verifies the token and reads only entitled tiers.
    draft_briefing composes from the served outputs (already-filtered data), and
    share_briefing stays the same non-sending stub. The model sees no brand/role param."""

    def __init__(self, brand: str, role: str, audit=None) -> None:
        email = ACCOUNT_EMAILS.get((brand, role))
        if email is None:
            raise KeyError(f"no seeded Firebase identity for ({brand!r}, {role!r})")
        self.brand = brand
        self.role = role
        self.email = email
        self._id_token = sign_in(email)  # one sign-in per run; identity is now the token
        self._brand_name: str | None = None
        self.audit = audit  # when set, each tool call is logged (Firestore sink in cli.py)

    # --- read tools (Cloud Functions) --------------------------------------

    def get_account_overview(self) -> dict:
        out = call_function("get_account_overview", self._id_token)
        if self._brand_name is None:
            self._brand_name = out.get("brand_name", self.brand)
        return out

    def get_contract_terms(self) -> dict:
        return call_function("get_contract_terms", self._id_token)

    def search_account_notes(self, query: str = "") -> dict:
        return call_function("search_account_notes", self._id_token, {"query": query})

    # --- composed / stub (client-side, from already-filtered data) ----------

    def draft_briefing(self) -> dict:
        # Compose from the Functions' SERVED output only — never a direct store read.
        overview = self.get_account_overview()
        terms = self.get_contract_terms()
        brand_name = overview.get("brand_name", self.brand)
        served_terms = terms.get("served", {})           # ordered by contract_field_index
        term_withheld = terms.get("withheld", [])
        ov_withheld = overview.get("withheld", [])
        return compose_briefing(self.brand, self.role, brand_name,
                                overview.get("served", {}), ov_withheld,
                                served_terms, term_withheld)

    def share_briefing(self, channel: str) -> dict:
        # Identical stub to Day 1: external writes pause for human approval.
        return {
            "status": "pending_human_approval",
            "destination": channel,
            "message": (
                f"Sharing the briefing to '{channel}' is an external write. It would "
                f"pause for explicit human approval with this destination shown. "
                f"(Stub — sending is not implemented in this phase.)"
            ),
        }

    def brand_label(self) -> str:
        """The bound brand's display name, fetched once via the overview Function."""
        if self._brand_name is None:
            self.get_account_overview()
        return self._brand_name or self.brand

    # --- dispatch (same contract as GovernedTools.dispatch) -----------------

    def dispatch(self, name: str, tool_input: dict) -> dict:
        try:
            if name == "get_account_overview":
                out = self.get_account_overview()
            elif name == "get_contract_terms":
                out = self.get_contract_terms()
            elif name == "search_account_notes":
                out = self.search_account_notes(tool_input.get("query", ""))
            elif name == "draft_briefing":
                out = self.draft_briefing()
            elif name == "share_briefing":
                out = self.share_briefing(tool_input.get("channel", ""))
            else:
                return {"error": f"unknown tool: {name}"}
        except FirebaseFunctionError as e:
            # A Function refusal surfaces as a tool error the agent can read, never as data.
            return {"error": e.message, "status": e.status}

        if self.audit is not None:
            self._audit(name, out)
        return out

    def _audit(self, name: str, out: dict) -> None:
        # Identical served/withheld normalization to GovernedTools._audit, so a Firebase-mode
        # tool_call line is the same shape as a Day 1 one — the substrate is all that changed.
        if name == "share_briefing":
            self.audit.external_write_pending(name, out.get("destination", ""))
            return
        if isinstance(out.get("served"), dict):
            served = list(out["served"].keys())
        elif "served_terms" in out:
            served = list(out["served_terms"])
        elif "matches" in out:
            served = [m.get("id") for m in out["matches"]]
        else:
            served = []
        self.audit.tool_call(name, served, out.get("withheld", []))
