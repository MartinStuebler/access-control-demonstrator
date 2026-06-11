"""A thin web FACE over the governed local backend. Presentation only — zero enforcement.

Every access decision is made by the existing, tested backend (`GovernedTools`,
`policy.decide`). This module never reads an account directly and never decides what is
visible; it calls the governed tools and renders what they return. If this file were
deleted, every security guarantee would be untouched, because none of them live here.

THE NO-LEAK GUARANTEE (the whole point):
  The browser receives ONLY served (entitled) values plus the NAMES of withheld fields.
  A withheld VALUE is never sent. This is structural, not a filter:
    - `GovernedTools._gather_contract_terms()` puts only {field, code, reason} into its
      withheld manifest — the value is never in a withheld record.
    - This endpoint builds the response from `served` (entitled) + `withheld[].field`
      (names). It never calls `store.get_account()`, so a withheld value is never even
      loaded into this layer's scope. It cannot leak what it never holds.

Run:  python -m web.app    (then open http://127.0.0.1:5055)  — offline, no API key.
"""
from __future__ import annotations

from flask import Flask, jsonify, render_template, request

# Reuse the EXACT local backend the CLI's `--backend local` and the tests use.
from src.policy import Principal, decide
from src.store import LocalJsonAccountStore
from src.tools import GovernedTools

app = Flask(__name__)

# One store for the process; it only reads the read-only synthetic JSON.
_store = LocalJsonAccountStore()
VALID_ROLES = ("sales", "legal", "power_user")


def _brands() -> list[dict]:
    """Brand ids + display names for the picker (display name is public identity)."""
    out = []
    for b in _store.list_brands():
        name = _store.get_account(b).get("brand_name", b)
        out.append({"id": b, "name": name})
    return out


def _brand_name(brand: str) -> str:
    return _store.get_account(brand).get("brand_name", brand)


def _withheld_names(withheld: list) -> list[str]:
    """Names ONLY, from the governed withheld manifest. Each entry is {field|section,
    code, reason} — there is no value to extract, which is exactly the point."""
    names = []
    for w in withheld:
        names.append(w.get("field") or w.get("section"))
    return names


@app.get("/")
def index():
    return render_template("index.html", brands=_brands(), roles=VALID_ROLES)


@app.post("/api/brief")
def api_brief():
    """Generate the governed brief for (brand, role). Returns served values + withheld
    NAMES. Built entirely from the governed tools' served/withheld outputs."""
    data = request.get_json(silent=True) or {}
    brand = data.get("brand", "")
    role = data.get("role", "")
    query = data.get("query", "Prepare my pre-call briefing for this account.")

    if brand not in _store.list_brands():
        return jsonify({"error": f"unknown brand {brand!r}"}), 400
    if role not in VALID_ROLES:
        return jsonify({"error": f"unknown role {role!r}"}), 400

    principal = Principal(brand=brand, role=role)
    tools = GovernedTools(_store, principal)

    # All three calls return {served: ..., withheld: [{field|section, code, reason}]}.
    overview = tools.get_account_overview()       # served sections, no withheld values
    terms = tools.get_contract_terms()            # served {field: value}, withheld names
    brief = tools.draft_briefing()                # rendered text (served + withheld names)

    # The response is assembled from served + names ONLY. No raw account is touched.
    return jsonify({
        "brand": brand,
        "brand_name": _brand_name(brand),
        "role": role,
        "query": query,
        "briefing": brief["briefing"],            # already contains no withheld value
        "overview": {
            "served": overview["served"],         # entitled sections
            "withheld": _withheld_names(overview["withheld"]),
        },
        "contract_terms": {
            "served": terms["served"],            # entitled {field: value}
            "withheld": _withheld_names(terms["withheld"]),   # NAMES ONLY
        },
    })


@app.post("/api/cross-brand")
def api_cross_brand():
    """Fire a cross-brand request through the REAL policy engine and show the refusal.
    Mirrors the CLI's --cross-brand-probe: it calls decide() against a rival brand and
    NEVER reads the rival's account — the block returns at the tenancy gate before any
    store access, so the rival brand is provably never accessed."""
    data = request.get_json(silent=True) or {}
    brand = data.get("brand", "")
    role = data.get("role", "")
    if brand not in _store.list_brands():
        return jsonify({"error": f"unknown brand {brand!r}"}), 400
    if role not in VALID_ROLES:
        return jsonify({"error": f"unknown role {role!r}"}), 400

    # Pick a rival = the first OTHER seeded brand.
    rival = next((b for b in _store.list_brands() if b != brand), None)
    if rival is None:
        return jsonify({"error": "no rival brand to probe"}), 400

    principal = Principal(brand=brand, role=role)
    # The single enforcement point decides. We pass "public" — the least sensitive tier —
    # to show even the most benign field of the rival is refused on the brand axis alone.
    d = decide(principal, rival, "public", _store.get_entitlements())

    return jsonify({
        "bound_brand": brand,
        "bound_brand_name": _brand_name(brand),
        "requested_brand": rival,
        "requested_brand_name": _brand_name(rival),
        "role": role,
        "refused": not d.allowed,
        "code": d.code,
        "reason": d.reason,
        # Structural truth: this endpoint only called decide(); it never read the rival
        # account. No rival field — not even a public one — was loaded or returned.
        "rival_accessed": False,
    })


if __name__ == "__main__":
    # Local only, fixed port, no debug reloader noise. Offline; no API key needed.
    app.run(host="127.0.0.1", port=5055, debug=False)
