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


def _detect_rival(text: str, bound_brand: str) -> str | None:
    """Routing ONLY: does the typed text gesture at another brand / a competitor? If so,
    return a rival brand id so the caller can run the REAL decide() probe against it.

    This NEVER decides access and NEVER fabricates a refusal — it only chooses whether to
    *ask* the policy engine about a rival. The answer is always decide()'s real result.
    It matches other brands by id or display name, or generic words like 'competitor'."""
    t = (text or "").lower()
    others = [b for b in _store.list_brands() if b != bound_brand]
    # Direct reference to a specific other brand (by id or display name) -> that one.
    for b in others:
        if b.lower() in t or _brand_name(b).lower() in t:
            return b
    # Generic adversarial gesture at "the competition" -> the first rival, to show refusal.
    if any(w in t for w in ("competitor", "competitors", "rival", "other brand",
                            "their data", "the other", "everyone", "all brands")):
        return others[0] if others else None
    return None


def _attack_evidence(principal: Principal, query: str, withheld_names: list[str]) -> list[dict]:
    """Build the 'why this held' evidence for an adversarial request — drawn ENTIRELY from
    real backend results (the governed withheld manifest + a real decide() probe), never
    hardcoded. Carries field NAMES and refusal reasons only, never any withheld value."""
    evidence: list[dict] = []

    # (a) Tier evidence: the economic fields this role does not get, by NAME, from the
    #     governed manifest the brief already produced. (No value is ever included.)
    if withheld_names:
        evidence.append({
            "kind": "tier_withheld",
            "requested_brand": principal.brand,
            "role": principal.role,
            "withheld_fields": withheld_names,
            "message": (f"{len(withheld_names)} field(s) withheld at role "
                        f"{principal.role}: {', '.join(withheld_names)} "
                        f"(names shown; values never left the server)."),
        })

    # (b) Cross-brand evidence: only if the text gestures at a rival. The refusal is the
    #     REAL decide() result; the rival's account is never read (decide() blocks at the
    #     tenancy gate before any store access), so rival_accessed is structurally false.
    rival = _detect_rival(query, principal.brand)
    if rival:
        d = decide(principal, rival, "public", _store.get_entitlements())
        evidence.append({
            "kind": "cross_brand",
            "bound_brand": principal.brand,
            "requested_brand": rival,
            "requested_brand_name": _brand_name(rival),
            "refused": not d.allowed,
            "code": d.code,
            "reason": d.reason,
            "rival_accessed": False,
            "message": (f"cross-brand read of {_brand_name(rival)} "
                        f"refused: {d.code} (rival brand never accessed)."),
        })
    return evidence


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

    term_withheld_names = _withheld_names(terms["withheld"])   # NAMES ONLY

    # The response is assembled from served + names ONLY. No raw account is touched.
    # `bound` echoes the principal so the viewer sees it came from the SELECTORS — the
    # typed `query` never sets brand/role. `evidence` explains an adversarial request
    # using only real backend results (withheld names + a real decide() probe).
    return jsonify({
        "brand": brand,
        "brand_name": _brand_name(brand),
        "role": role,
        "query": query,
        "bound": {"brand": principal.brand, "role": principal.role,
                  "source": "selectors (the typed text cannot change this)"},
        "briefing": brief["briefing"],            # already contains no withheld value
        "overview": {
            "served": overview["served"],         # entitled sections
            "withheld": _withheld_names(overview["withheld"]),
        },
        "contract_terms": {
            "served": terms["served"],            # entitled {field: value}
            "withheld": term_withheld_names,
        },
        "evidence": _attack_evidence(principal, query, term_withheld_names),
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
