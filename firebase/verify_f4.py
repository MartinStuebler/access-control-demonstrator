"""F4 end-to-end verification (runs against the emulator).

Exercises the REAL Firebase path the agent uses: sign in to the Auth emulator, call the
callable Functions with the signed token, and assert what each role is served vs denied.
Then proves the two defense layers both refuse a cross-brand read, that no-claims /
unknown-role / unauthenticated callers are refused, and that the deterministic brief is
byte-identical between local (Day 1 tools) and firebase (Functions) for every principal.

    cd firebase && python3 verify_f4.py        # emulator must be running

Prints a matrix; exits non-zero on any miss.
"""
from __future__ import annotations

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

# Import the Day 1 + Firebase code from the repo (this file lives under firebase/).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.fb_backend import (  # noqa: E402
    FUNCTIONS_BASE, FunctionsTools, FirebaseFunctionError, call_function, sign_in,
)
from src.policy import Principal  # noqa: E402
from src.store import LocalJsonAccountStore  # noqa: E402
from src.tools import GovernedTools  # noqa: E402

AUTH = "http://127.0.0.1:9099/identitytoolkit.googleapis.com/v1"
FS = "http://127.0.0.1:8080/v1/projects/demo-access-control/databases/(default)/documents"

SEEDED = [  # (brand, role) — the six seeded identities (brand_c is rules-symmetry only)
    ("brand_a", "sales"), ("brand_a", "legal"), ("brand_a", "power_user"),
    ("brand_b", "sales"), ("brand_b", "legal"), ("brand_b", "power_user"),
]

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


def _claims(tok: str) -> dict:
    p = tok.split(".")[1]
    p += "=" * (-len(p) % 4)
    return json.loads(base64.urlsafe_b64decode(p))


def main() -> int:
    print("F4 FUNCTION-LAYER VERIFICATION  (Auth + Firestore + Functions emulator)")
    print("=" * 78)

    # (1) Per-role served / withheld through get_contract_terms (the field boundary).
    print("\n-- get_contract_terms: served vs withheld, per role (own brand) --")
    for brand, role in SEEDED:
        t = FunctionsTools(brand, role)
        ct = t.get_contract_terms()
        served, withheld = set(ct["served"]), {w["field"] for w in ct["withheld"]}
        blob = json.dumps(ct)
        if role == "sales":
            ok = ("minimum_order_quantity" in served and "unit_price" not in served
                  and {"unit_price", "margin_floor"} <= withheld
                  and "EUR 420" not in blob)  # economic VALUE never present
            check(f"{role}@{brand}: operational served, economic withheld & valueless",
                  ok, f"served={len(served)} withheld={len(withheld)}")
        else:  # legal / power_user
            ok = ("unit_price" in served and ct["served"].get("unit_price")
                  and not withheld)
            check(f"{role}@{brand}: economic served too, nothing withheld",
                  ok, f"served={len(served)} withheld={len(withheld)}")

    # (2) Two layers both refuse a cross-brand read.
    print("\n-- cross-brand: BOTH layers refuse (brand_b reaching brand_a) --")
    tok_b = sign_in("sales@solene.demo")  # brand_b token
    # Layer 2 (Function): a smuggled data.brand is ignored; identity is the token = brand_b.
    smuggled = call_function("get_account_overview", tok_b, {"brand": "brand_a"})
    check("L2 Function: brand_b token + smuggled brand=brand_a -> serves brand_b only",
          smuggled.get("brand") == "brand_b" and "brand_a" not in json.dumps(smuggled),
          f"returned brand={smuggled.get('brand')}")
    # Layer 1 (rules): a raw client read of brand_a with the brand_b token is denied at the DB.
    own = _req("GET", f"{FS}/accounts_operational/brand_b", headers={"Authorization": f"Bearer {tok_b}"})[0]
    cross = _req("GET", f"{FS}/accounts_operational/brand_a", headers={"Authorization": f"Bearer {tok_b}"})[0]
    check("L1 rules: raw client read brand_b->brand_b = 200 (control)", own == 200, f"HTTP {own}")
    check("L1 rules: raw client read brand_b->brand_a = 403 DENIED", cross == 403, f"HTTP {cross}")

    # (3) No-claims, unknown-role, and unauthenticated callers are all refused by the Function.
    print("\n-- fail-closed identities refused at the Function (ties to F1 + F3) --")
    # Fresh throwaway identity each run (the emulator keeps users until restart), so the
    # no-claims assertion is never polluted by a prior run's claim.
    adversary_email = f"adversary-{os.getpid()}-{int(time.time())}@test.demo"
    up = _req("POST", f"{AUTH}/accounts:signUp?key=demo",
              {"email": adversary_email, "password": "demo-password", "returnSecureToken": True})[1]
    noclaims_tok, uid = up["idToken"], up["localId"]
    check("no-claims token carries no brand/role",
          _claims(noclaims_tok).get("brand") is None and _claims(noclaims_tok).get("role") is None)
    for label, tok in [("no-claims", noclaims_tok), ("unauthenticated", "")]:
        try:
            call_function("get_contract_terms", tok)
            check(f"{label} token -> get_contract_terms refused", False, "served data!")
        except FirebaseFunctionError as e:
            check(f"{label} token -> get_contract_terms refused", True, e.status)
    # Unknown/garbage role: set a bad claim via the emulator admin endpoint, re-sign-in.
    _req("POST", f"{AUTH}/projects/demo-access-control/accounts:update",
         {"localId": uid, "customAttributes": json.dumps({"brand": "brand_a", "role": "intruder"})},
         {"Authorization": "Bearer owner"})
    intruder_tok = sign_in(adversary_email)
    check("intruder token carries role=intruder", _claims(intruder_tok).get("role") == "intruder")
    try:
        call_function("get_contract_terms", intruder_tok)
        check("unknown-role token -> get_contract_terms refused", False, "served data!")
    except FirebaseFunctionError as e:
        check("unknown-role token -> get_contract_terms refused", True, e.status)

    # (4) Same governed brief, substrate swapped: firebase Functions vs Day 1 local tools.
    print("\n-- draft_briefing byte-identical: firebase (Functions) vs local (Day 1) --")
    store = LocalJsonAccountStore()
    for brand, role in SEEDED:
        fb = FunctionsTools(brand, role).draft_briefing()["briefing"]
        local = GovernedTools(store, Principal(brand=brand, role=role)).draft_briefing()["briefing"]
        check(f"{role}@{brand}: briefs identical", fb == local,
              "identical" if fb == local else f"DIFFER ({len(fb)} vs {len(local)} chars)")

    print("\n" + "=" * 78)
    print(f"RESULT: {passed}/{passed + failed} checks passed" + (f"  ({failed} FAILED)" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
