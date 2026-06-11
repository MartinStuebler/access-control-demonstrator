"""F5 end-to-end verification — audit to Firestore, Admin-path only (emulator).

Exercises the REAL audit path the agent uses in firebase mode:
    AuditLog -> FirestoreAuditSink -> log_audit Function (Admin SDK) -> `audit` collection
(the model only chooses WHICH tools to call; the audit wiring is deterministic, so this
verifier drives the tools directly, exactly as verify_f4.py does for the read path).

It then proves the integrity properties that make the trail evidence:
  - a Firebase-mode run writes run_start, tool_calls (served/withheld), run_end, and a
    cross_brand_block (operator-initiated) to Firestore, all scoped to the bound brand;
  - identity on each line is server-authoritative: a record that tries to forge brand_b
    is stored as the token's brand_a;
  - an authenticated ORDINARY seeded user (not anonymous) is denied a client WRITE and a
    client DELETE to `audit` (403) — append-only via the Admin path, tamper-evident.

    cd firebase && python3 verify_f5.py        # emulator must be running

Prints a matrix; exits non-zero on any miss.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

# Import the Day 1 + Firebase code from the repo (this file lives under firebase/).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.audit import AuditLog  # noqa: E402
from src.fb_backend import FunctionsTools, FirestoreAuditSink, sign_in  # noqa: E402
from src.policy import Principal  # noqa: E402

FS = "http://127.0.0.1:8080/v1/projects/demo-access-control/databases/(default)/documents"
OWNER = {"Authorization": "Bearer owner"}  # emulator owner bypasses rules (Admin-equivalent)

passed = 0
failed = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global passed, failed
    passed, failed = passed + (1 if ok else 0), failed + (0 if ok else 1)
    tail = f"  ({detail})" if detail else ""
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}{tail}")


def _req(method, url, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method,
                               headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(r) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}


def _decode(value: dict):
    """Decode one Firestore REST typed value into a plain Python value."""
    if "stringValue" in value:
        return value["stringValue"]
    if "integerValue" in value:
        return int(value["integerValue"])
    if "doubleValue" in value:
        return value["doubleValue"]
    if "booleanValue" in value:
        return value["booleanValue"]
    if "nullValue" in value:
        return None
    if "timestampValue" in value:
        return value["timestampValue"]
    if "arrayValue" in value:
        return [_decode(v) for v in value["arrayValue"].get("values", [])]
    if "mapValue" in value:
        return {k: _decode(v) for k, v in value["mapValue"].get("fields", {}).items()}
    return None


def _decode_doc(doc: dict) -> dict:
    return {k: _decode(v) for k, v in doc.get("fields", {}).items()}


def read_audit(run_id: str) -> list[dict]:
    """Read the whole audit collection via the owner endpoint, return this run's docs."""
    status, body = _req("GET", f"{FS}/audit?pageSize=1000", headers=OWNER)
    docs = [_decode_doc(d) for d in body.get("documents", [])]
    return [d for d in docs if d.get("run_id") == run_id]


def doc_ids(run_id: str) -> list[str]:
    status, body = _req("GET", f"{FS}/audit?pageSize=1000", headers=OWNER)
    out = []
    for d in body.get("documents", []):
        if _decode_doc(d).get("run_id") == run_id:
            out.append(d["name"].split("/documents/")[1])  # e.g. audit/<id>
    return out


def main() -> int:
    print("F5 AUDIT-TO-FIRESTORE VERIFICATION  (Auth + Firestore + Functions emulator)")
    print("=" * 78)

    run_id = f"verify-f5-{os.getpid()}-{int(time.time())}"
    principal = Principal(brand="brand_a", role="sales")
    token_a = sign_in("sales@lirelle.demo")  # ordinary seeded user, brand_a / sales

    # --- drive a governed firebase-mode run through the REAL audit path ---------------
    sink = FirestoreAuditSink(token_a)
    audit = AuditLog(principal, run_id=run_id, sink=sink)
    tools = FunctionsTools("brand_a", "sales", audit=audit)

    audit.run_start("Prep my pre-call briefing.")
    tools.dispatch("get_account_overview", {})
    tools.dispatch("get_contract_terms", {})           # logs served (operational) + withheld (economic)
    tools.dispatch("search_account_notes", {"query": "sample"})
    tools.dispatch("draft_briefing", {})
    audit.run_end("completed")
    # Operator cross-brand probe -> operator-initiated block on the trail.
    audit.cross_brand_block(
        "brand_b", "cross-brand read refused at both layers (probe)", initiated_by="operator_probe")

    time.sleep(0.4)  # let the Admin writes settle in the emulator before reading back
    trail = read_audit(run_id)

    # --- (1) the run's events are all present, in the trail ---------------------------
    print("\n-- a firebase-mode run writes its trail to the Firestore `audit` collection --")
    events = [d.get("event") for d in trail]
    check("run_start present", "run_start" in events, f"{len(trail)} docs for this run")
    check("run_end present", "run_end" in events)
    tool_calls = [d for d in trail if d.get("event") == "tool_call"]
    check("tool_call lines present for each read tool", len(tool_calls) >= 4,
          f"{len(tool_calls)} tool_call docs")

    # --- (2) get_contract_terms recorded served (operational) + withheld (economic) ---
    ct = next((d for d in tool_calls if d.get("tool") == "get_contract_terms"), None)
    served = (ct or {}).get("served", [])
    withheld_fields = {w.get("field") for w in (ct or {}).get("withheld", [])}
    check("get_contract_terms: operational fields recorded as served",
          ct is not None and "minimum_order_quantity" in served and "unit_price" not in served,
          f"served={served}")
    check("get_contract_terms: economic fields recorded as withheld (names, no values)",
          {"unit_price", "margin_floor"} <= withheld_fields
          and "EUR 420" not in json.dumps(ct or {}),
          f"withheld={sorted(withheld_fields)}")

    # --- (3) every line of this run is scoped to brand_a; nothing from another brand ---
    brands = {d.get("brand") for d in trail}
    check("every audit line scoped to the bound brand (brand_a), nothing else",
          brands == {"brand_a"}, f"brands seen = {sorted(brands)}")

    # --- (4) the cross-brand block is present and marked operator-initiated ------------
    block = next((d for d in trail if d.get("event") == "cross_brand_block"), None)
    check("cross_brand_block present, initiated_by=operator_probe (not the model)",
          block is not None and block.get("initiated_by") == "operator_probe"
          and block.get("requested_brand") == "brand_b" and block.get("brand") == "brand_a",
          f"initiated_by={(block or {}).get('initiated_by')}")

    # --- (5) identity is server-authoritative: a forged brand is overwritten ----------
    print("\n-- identity on the stored line is server-stamped from the token, not the client --")
    sink({"ts": "1999-01-01T00:00:00Z", "run_id": run_id, "event": "forge_attempt",
          "brand": "brand_b", "role": "legal", "note": "client tried to forge brand_b/legal"})
    time.sleep(0.3)
    forged = next((d for d in read_audit(run_id) if d.get("event") == "forge_attempt"), None)
    check("client-sent brand=brand_b stored as token's brand_a (overwritten)",
          forged is not None and forged.get("brand") == "brand_a", f"stored brand={(forged or {}).get('brand')}")
    check("client-sent role=legal stored as token's role sales (overwritten)",
          forged is not None and forged.get("role") == "sales", f"stored role={(forged or {}).get('role')}")
    check("client-sent ts (1999) replaced by the server clock",
          forged is not None and not str(forged.get("ts", "")).startswith("1999"),
          f"stored ts={(forged or {}).get('ts')}")

    # --- (6) integrity: an authenticated ordinary user cannot write or delete audit ----
    print("\n-- authenticated ordinary user (sales@lirelle.demo) denied write + delete on audit --")
    # Client WRITE attempt via the Firestore REST API, carrying a REAL seeded user token.
    w_status, _ = _req(
        "POST", f"{FS}/audit?documentId=client_forged_{os.getpid()}",
        {"fields": {"event": {"stringValue": "forged_by_client"},
                    "brand": {"stringValue": "brand_b"}}},
        headers={"Authorization": f"Bearer {token_a}"})
    check("client WRITE to audit (logged-in sales user) -> 403 DENIED", w_status == 403, f"HTTP {w_status}")
    # Client DELETE attempt on a REAL audit doc from this run, same seeded user token.
    ids = doc_ids(run_id)
    target = ids[0] if ids else "audit/nonexistent"
    d_status, _ = _req("DELETE", f"{FS}/{target}", headers={"Authorization": f"Bearer {token_a}"})
    check("client DELETE of an audit doc (logged-in sales user) -> 403 DENIED", d_status == 403,
          f"HTTP {d_status} on {target}")
    # Bonus: the trail is not even client-readable (allow read: if false).
    r_status, _ = _req("GET", f"{FS}/audit", headers={"Authorization": f"Bearer {token_a}"})
    check("client READ of audit (logged-in sales user) -> 403 DENIED (evidence, not user data)",
          r_status == 403, f"HTTP {r_status}")

    print("\n" + "=" * 78)
    print(f"RESULT: {passed}/{passed + failed} checks passed" + (f"  ({failed} FAILED)" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
