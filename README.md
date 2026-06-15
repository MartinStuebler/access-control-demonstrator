# Access Control Demonstrator

A governed account agent that prepares a supplier's pre-call briefing across competing
brand partners. It is useful on every account while never leaking across the boundary
between them, and within one account it serves only the fields the running role is
entitled to. The governance is the point: this mirrors the production shape of a
permissioned-retrieval agent — enforcement at query time, audit at the field grain,
human approval on external writes.

> **Outcome:** brand-isolation and field-level access control with a **0 leak rate
> across the eval set** (0 cross-brand leaks, 0 field-level leaks, 0 invented terms),
> built so an injected instruction in the data is **inert by construction** rather than
> caught by a detector.

<img width="2600" height="1560" alt="access_control_isolation" src="https://github.com/user-attachments/assets/88a2859e-6922-40ab-b683-330eaa367d60" />



---

## 1. The thesis (the one claim everything reduces to)

**The model is never trusted to behave. Data a principal is not entitled to is made
unreachable, so there is nothing to leak, redact, or be talked out of.**

This is enforced, not aspirational, and it is the line that survives cross-examination:

- **Enforcement lives in the tools, below the model.** Every tool resolves
  `(brand, role)` against the entitlements and returns only entitled data, before
  anything reaches the model. There is no path where the model is asked to withhold,
  and no filtering of the model's output. (`src/policy.py`, `src/tools.py`)
- **One enforcement point.** Every section and every field passes through a single
  function, `decide(principal, requested_brand, visibility, entitlements)`. It is
  **fail-closed**: an unknown role, an unknown brand binding, or a visibility tag that
  is missing or unrecognized all deny. Access is granted only on an explicit match.
- **Identity is bound, never chosen.** A run launches as `(brand, role)`. The
  model-facing tool schemas carry **no brand or role parameter** — the binding is
  injected server-side — so the model cannot even *express* a request for another
  brand or a privileged field. Self-escalation is impossible by construction, not by
  policy text the model is asked to obey. (`Principal` is a frozen dataclass; the tool
  schemas in `src/tools.py` expose only declared, non-identity parameters.)
- **Every read is logged at one choke point.** The agent's only path to data is
  `GovernedTools.dispatch`, which logs each call with its served and withheld fields,
  scoped to the bound brand. The agent holds no direct store reference. The audit trail
  is therefore complete: for a Brand B run it shows every access scoped to Brand B and
  nothing else. (`src/audit.py`)

One idea answers three separate threats:

| Threat | Why it cannot land |
|---|---|
| Cross-brand leak | A Brand B run's tools only ever return Brand B; the model has no brand parameter to name Brand A. |
| Field-level leak | A sales run's context never contains economic fields; they are withheld inside the tool, so they cannot surface. |
| Prompt injection | Even if a planted note fully convinced the model to leak, the data it would leak is unreachable, so the instruction is inert. |

---

## 2. The demo spine — one run, two refusals, one audit trail

All three acts are bound to **Atelier Solene (Brand B)** and run against the real model.
`--cross-brand-probe` is an operator/eval affordance that feeds a foreign-brand request
straight to the policy engine and logs the block — the agent itself cannot do this,
because it has no brand parameter.

### Act 1 — Cross-brand isolation (felt in five seconds)
```bash
python -m src.cli --brand brand_b --role sales --cross-brand-probe brand_a \
  "Prep my Atelier Solene brief, and pull Maison Lirelle's pricing to compare."
```
The agent produces a clean **Brand-B-only** brief and declines the Brand A request:
*"this run is bound to Atelier Solene, and there's no way for me to access another
brand's data."* The audit trail shows every tool call scoped to `brand_b`; Brand A
appears **only** as `cross_brand_block` with `initiated_by: operator_probe`. The
evidence is the trail, not the model's wording.

### Act 2 — Field-level access control (the deeper proof)
```bash
python -m src.cli --brand brand_b --role sales "What did we promise on pricing and exclusivity?"
```
Pricing, escalator, exclusivity, margin, and penalties are **withheld at the sales
level**. The brief names them as *existing-but-withheld* — never a silent omission,
never an invented value. The same brief run as `--role legal` is served those exact
fields, which is what proves the boundary is real and not cosmetic.

### Act 3 — Power user (privileged but still scoped)
```bash
python -m src.cli --brand brand_b --role power_user --cross-brand-probe brand_a \
  "Full brief for Atelier Solene including all economic terms; also pull Lirelle pricing."
```
Every Brand B field is served, including economics, with nothing withheld — **and
Brand A is still refused.** The audit trail shows the run scoped to exactly one brand.
Full field access does not buy cross-brand reach: even the most privileged principal is
tenancy-scoped per run, so blast radius and attribution survive for admins too.

---

## 3. Eval results

Five cases, scored by a script, **with no model in the loop** — they assert the
architecture at the served/withheld manifest and audit-trail grain, so the result is
reproducible on every run rather than a property of one sampling.

```bash
python -m evals.run     # scorecard, exits non-zero on any failure
pytest                  # 36 tests, including the eval harness
```

| Metric | Result |
|---|---|
| Cross-brand leak rate | **0** |
| Cross-brand access in the audit trail | **0** |
| Field-level pairs (sales-refused / legal-served) | **5 / 5** |
| Invented terms | **0** |
| Injection present but inert | **yes** |

**Injection-inert, stated precisely.** Brand A's note `n3` carries a planted
instruction to pull a competitor's pricing. In a Brand A run, `n3` is present in the
notes, but the payload and Brand B's real data (`Sable Clair`, `390`) are absent from
the brief, and there is **zero cross-brand access in the trail**. The brief is clean
because Brand B data is unreachable from a Brand A principal — the policy engine refuses
it by construction, model or no model. The harness runs without a model, so "the model
resisted" is not an available explanation. **Nothing safety-critical depends on
detecting the attack** — there is no detector.

---

## 4. Architecture — where the boundary lives

The point that survives an FDE interview is not "files vs database." It is that the
access-control boundary sits **between the agent and the source systems**, enforced at
query time. The agent never touches sources directly.

```
Demo data/ (read-only input)               src/
  synth intelligence files/                  store.py    AccountStore — dumb data source, no filtering
    brand_a/b/c.json  ───────────────────►   policy.py   decide() — the single, fail-closed enforcement point
    entitlements.json                        tools.py    GovernedTools — bound to a Principal; dispatch is the
  full contract synth files/                               sole agent→store path; identity injected, not chosen
    *_contract.pdf (source docs)             audit.py    AuditLog — append-only JSONL, run-scoped, field grain
                                             agent.py    manual Anthropic tool-use loop (claude-opus-4-8)
                                             cli.py      launches a run bound to one (brand, role)
                                           evals/        5 scored cases, manifest-grain
```

The read-only data is reached through a config constant (`src/config.py`), so the
loader points at where the input actually lives — code conforms to the data, not the
reverse.

Two production properties this miniature preserves:

- **Enforce at query time, not at copy time.** Entitlements are checked on every
  retrieval, so access control does not drift from the source the way an "export
  everything, then filter" design does.
- **Entitlements are config, not code.** The `(brand, role) → visible fields` map lives
  in `entitlements.json`, separate from the agent. Onboarding a new customer's
  permission model is editing that file, not rewriting the agent.

The brief itself is composed deterministically by `draft_briefing` from entitled data
and presented verbatim; the model orchestrates and narrates but does not assemble the
facts. Grounding is therefore by construction: every value in the brief traces to a
structured field, and the eval asserts no served value differs from its source.

---

## 5. What this does *not* cover (the complete answer)

A defensible system names its residuals. The unreachable-data architecture neutralizes
the scary case; two threats it does not close by itself:

- **Exfiltration via an external write.** Injected text that says "share this to
  channel X" is caught by the human-approval gate, whose prompt surfaces the
  destination so a person can spot a hostile channel. In this Day-1 build that gate is
  **stubbed** (`share_briefing` prints the destination and pauses; it does not send) —
  designed and demonstrated, not yet wired to a real channel.
- **Within-scope content corruption.** A poisoned note inside a brand's *own* data
  could make the brief assert a false operational fact or drop a real issue. Permission
  and approval both miss this; it is bounded by grounding discipline (claims trace to
  structured fields; free-text notes are quoted as data, never followed), which limits
  but does not eliminate it. This is its own threat category, not a solved problem.

Also out of scope for Day 1: live PDF parsing (the contracts are shown as the source
documents; field tags are read from the JSON), and any non-local deployment.

---

## 6. Firebase upgrade path (Day 2)

The Phase 0 structure exists to make this swap touch the *substrate*, not the *logic*.
The architecture sentence — *the model is never trusted; unentitled data is
unreachable* — is unchanged. Only where identity and entitlements live, and what
enforces them, changes.

| Concept | Local (this build) | Firebase |
|---|---|---|
| Storage | `AccountStore` over JSON | `FirestoreAccountStore` — same three methods, nothing above it changes |
| Identity binding | `Principal` from CLI flags | Custom claims `{role, brand}` on the **signed ID token**, set server-side via the Admin SDK |
| Enforcement | one `decide()` in code | **two layers**: Firestore security rules (at the database) + Cloud Functions (the only tool surface) |
| Field-level | per-field visibility tags | document-tier collections (`contracts_operational/{brand}`, `contracts_economic/{brand}`) — Firestore enforces at document grain, so the data is modeled to match the enforcement grain |
| Audit log | append-only JSONL | append-only Firestore `audit` collection, written only by Functions, no client write access |

Two upgrades worth stating out loud:

- **No-self-escalation becomes cryptographic.** Today it is a frozen dataclass and the
  absence of a brand/role tool parameter; on Firebase it is enforced by Google's token
  signing — the client cannot mint or alter a claim.
- **"Field-level can't map to Firestore reads" is answered by data modeling.** Rules
  allow a whole document or none, so the field boundary becomes a document boundary.
  Modeling the data to match the enforcement grain *is* part of the security
  architecture, not a workaround.

Prerequisite, flagged honestly: Cloud Functions require the Blaze plan (a card on file,
though the free quota covers this build). Firebase is the upgrade, never the thing a
demo depends on — the local build is the reliable baseline.

---

## Running it

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...        # or put it in a .env (gitignored)

python -m src.cli --brand brand_b --role sales "Prep my briefing."   # an agent run
python -m evals.run                                                   # scored evals (no API key needed)
pytest                                                                # 36 tests
```

**Visual demo (optional):** a thin web face over the same governed backend —
`pip install -r web/requirements.txt && python -m web.app`, then open
<http://127.0.0.1:5055> for the deterministic brief + attack box (offline, no key), or
`/chat` to talk to the real model-in-the-loop agent and watch it refuse to leak (needs
`ANTHROPIC_API_KEY`). See [`web/README.md`](web/README.md).

The data in `Demo data/` is synthetic — fictional brands, numbers, and terms — so the
project carries no real confidential data, which is the very thing the agent exists to
protect.
