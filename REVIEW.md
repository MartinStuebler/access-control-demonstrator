# F5 review — audit to Firestore + console walkthrough

**Status: built, all tests green, merged to `main`.** Read this once; the last section
lets you confirm every claim live in ~15 minutes without rebuilding anything.

- Branch `f5-audit-firestore` → merged to `main` as `efa8531` (no-ff). Working tree clean.
- `Demo data/` untouched. Local mode unchanged. Day 1 Python suite still 36/36.
- Emulator-only throughout: no cloud deploy, no Blaze, no billing.

---

## 1. What was built

**The goal:** give the audit log a Firestore sink so a Firebase-mode run leaves a trail
that is *evidence* — one a client cannot forge or erase — and rehearse the live console
walkthrough that closes the demo.

| # | Change | File |
|---|---|---|
| 1 | **`log_audit` callable Function** — the Admin-path audit sink. Verifies the token, stamps `brand`/`role`/`ts` server-side, append-only. | `firebase/functions/index.js` |
| 2 | **One interface, two sinks.** `AuditLog` gains a pluggable `sink`; default = JSONL (Day 1, unchanged), firebase = Firestore. Record assembly written once. | `src/audit.py` |
| 3 | **`FirestoreAuditSink`** + audit wiring into `FunctionsTools` (tool calls log served/withheld, same normalization as Day 1). | `src/fb_backend.py` |
| 4 | **Firebase run wires audit** to both Agent (run_start/end) and tools; `--cross-brand-probe` logs an operator-initiated block. | `src/cli.py` |
| 5 | **Explicit `/audit/{entry}` rule** — `read`+`write` both `if false` (denies client write *and* delete). | `firebase/firestore.rules` |
| 6 | **Rules suite +2** (audit write+delete deny) and **isolated into its own project** so it no longer clobbers demo data. 78 → **80**. | `firebase/rules/assert_rules.js` |
| 7 | **`verify_f5.py`** — 13-check end-to-end audit matrix. | `firebase/verify_f5.py` |
| 8 | **`DEMO.md`** console walkthrough + README F5 section. | `DEMO.md`, `firebase/README.md` |

**The design in one breath:** the Python backend signs in as an ordinary user, which has
only client privileges, and the F3 rules deny *every* client write to `audit`. So the only
way to append is the `log_audit` Function, which writes with the Admin SDK (bypassing
rules) and re-derives `brand`/`role` from the verified token. No client path can write,
update, or delete a line. That is what makes the trail evidence.

---

## 2. Every test and its result

Run against the live emulator (commands in §5). All green:

| Suite | Command | Result |
|---|---|---|
| Day 1 Python (local mode, offline) | `python -m pytest -q` | **36 passed** |
| Firestore rules assertions | `cd firebase && npm run rules:test` | **80 / 80** |
| F4 function-layer matrix | `python3 firebase/verify_f4.py` | **20 / 20** |
| F5 audit-to-Firestore matrix | `python3 firebase/verify_f5.py` | **13 / 13** |

> **One thing I changed beyond the F5 scope, and why.** The rules suite seeded its
> throwaway docs into the *same* emulator project (`demo-access-control`), overwriting the
> migrated `accounts_*` docs — so running `rules:test` before the verifiers silently wiped
> `contract_field_index` and made reads come back empty. I isolated the suite into its own
> project id (`demo-rules-test`); it still asserts the real `firestore.rules`, still 80/80,
> but no longer touches demo data. The battery is now order-independent. (This was a
> latent F3-era footgun, surfaced by running everything together.)

### F5's 13 checks, in detail

```
-- a firebase-mode run writes its trail to the Firestore `audit` collection --
  [PASS] run_start present
  [PASS] run_end present
  [PASS] tool_call lines present for each read tool
  [PASS] get_contract_terms: operational fields recorded as served
  [PASS] get_contract_terms: economic fields recorded as withheld (names, no values)
  [PASS] every audit line scoped to the bound brand (brand_a), nothing else
  [PASS] cross_brand_block present, initiated_by=operator_probe (not the model)
-- identity on the stored line is server-stamped from the token, not the client --
  [PASS] client-sent brand=brand_b stored as token's brand_a (overwritten)
  [PASS] client-sent role=legal stored as token's role sales (overwritten)
  [PASS] client-sent ts (1999) replaced by the server clock
-- authenticated ordinary user (sales@lirelle.demo) denied write + delete on audit --
  [PASS] client WRITE to audit (logged-in sales user) -> 403 DENIED
  [PASS] client DELETE of an audit doc (logged-in sales user) -> 403 DENIED
  [PASS] client READ of audit (logged-in sales user) -> 403 DENIED (evidence, not user data)
```

---

## 3. The audit-integrity proofs (the headline)

**Claim: an authenticated, ordinary seeded user cannot forge or erase the audit log.**

The `403`s in `verify_f5.py` come from `sales@lirelle.demo` — a **real signed-in seeded
user**, not anonymous — hitting the Firestore REST API directly with its token:

- **Write denied:** `POST …/documents/audit` with the user's Bearer token → `403`.
- **Delete denied:** `DELETE …/documents/audit/<real-doc-id>` with the user's token → `403`.
- **Read denied:** `GET …/documents/audit` with the user's token → `403` (the trail is
  operator evidence, shown via the Admin console, not a user-readable collection).

The rule that enforces it (`firebase/firestore.rules`):

```
match /audit/{entry} {
  allow read:  if false;   // evidence: Admin/console-only, not client-readable
  allow write: if false;   // create, update, AND delete denied for every client
}
```

In Firestore, `write` = create + update + delete, so that one line blocks a forged append
*and* an erase. The only writer is the Admin-path `log_audit` Function (bypasses rules).

**Server-authoritative identity:** `verify_f5.py` sends an audit record claiming
`brand=brand_b, role=legal, ts=1999-…` through the sink; it is stored as `brand=brand_a,
role=sales, ts=<server-now>` — proving the stored scope is the verified token's, never the
client's input.

---

## 4. The cross-brand refusal, both layers

A `brand_b` caller cannot reach `brand_a`, refused independently at each layer:

- **Layer 2 (Function, F4):** there is no brand parameter; a smuggled `data.brand` is
  ignored — identity is the token. `verify_f4.py`:
  `L2 Function: brand_b token + smuggled brand=brand_a -> serves brand_b only`.
- **Layer 1 (rules, F3):** a raw client read of `brand_a` with a `brand_b` token is denied
  at the database. `verify_f4.py`: `L1 rules: raw client read brand_b->brand_a = 403
  DENIED` (with a `200` same-brand control beside it).
- **On the trail (F5):** the operator probe lands as a `cross_brand_block` document with
  `initiated_by=operator_probe` and `requested_brand=brand_b`, while the run's scope stays
  `brand=brand_a`. The agent has no brand parameter, so a block is *always* operator-
  initiated, never "the model tried."

Here is a **real, model-in-the-loop run** I captured (`run_id=20260611T152330-ebb317`),
read back from Firestore — note every line is `brand=brand_a`, economic fields are
withheld by **name only**:

```
[15:23:30] run_start          brand=brand_a role=sales
[15:23:33] tool_call          brand=brand_a role=sales  tool=get_account_overview  served=[profile,orders,open_issues,last_contact]
[15:23:33] tool_call          brand=brand_a role=sales  tool=get_contract_terms    served=[term_length,delivery_lead_time,minimum_order_quantity,annual_volume_commitment,sample_obligations]  withheld=[unit_price,price_escalator,exclusivity,margin_floor,late_delivery_penalty]
[15:23:33] tool_call          brand=brand_a role=sales  tool=draft_briefing        served=[…operational…]  withheld=[…economic names…]
[15:23:41] run_end            brand=brand_a role=sales
[15:23:41] cross_brand_block  brand=brand_a role=sales  requested=brand_b  initiated_by=operator_probe
```

---

## 5. Confirm it yourself — copy-paste, ~15 minutes, no rebuild

Everything below runs against the local emulator. You are on `main`, tree clean.

### A. Start the emulator (terminal 1) — leave it running
```bash
cd ~/Documents/my_projects/access-control-layer/firebase
export PATH="/opt/homebrew/opt/openjdk/bin:$PATH"     # Firestore emulator needs Java
npm run emulators                                      # Auth + Firestore + Functions + UI
```
Wait for `All emulators ready`. (If a stale emulator is already running, kill it first:
`pkill -f "firebase emulators:start"`.)

### B. Seed + migrate, then run the whole battery (terminal 2)
```bash
cd ~/Documents/my_projects/access-control-layer
source .venv/bin/activate
export PATH="/opt/homebrew/opt/openjdk/bin:$PATH"

cd firebase && npm run seed && npm run migrate && cd ..

python -m pytest -q                 # Day 1, local mode, offline  -> 36 passed
cd firebase
npm run rules:test                  # -> 80/80
python3 verify_f4.py                # -> 20/20
python3 verify_f5.py                # -> 13/13   (the audit + 403 deny proofs)
cd ..
```

### C. See a governed run + its audit trail live
```bash
# A governed sales run: operational terms served, economic fields named-but-withheld.
python -m src.cli --backend firebase --brand brand_a --role sales "Prep my briefing."

# Same, plus the operator cross-brand probe (logs an operator-initiated block):
python -m src.cli --backend firebase --brand brand_a --role sales \
  --cross-brand-probe brand_b "Prep my briefing."
# ^ note the run_id in the terminal footer.
```
Open **<http://localhost:4000>** → **Firestore** → `audit`. Sort by `ts`, find your
`run_id`: you'll see `run_start`, the `tool_call`s (economic field **names** withheld, no
values), `run_end`, and the `cross_brand_block` (`initiated_by=operator_probe`). Every doc
is `brand=brand_a`. Then open the **Rules** tab to see the `/audit/{entry}` block and the
brand/tier gates that enforced all of it. (Full beat-by-beat script: `DEMO.md`.)

### D. Watch a cross-brand denial at the database (optional, raw)
```bash
# verify_f4.py already shows this; to eyeball the raw 403, the two lines to read are:
python3 firebase/verify_f4.py | grep -E "L1 rules|L2 Function"
```

### Local-mode fallback still works offline (no emulator)
```bash
python -m src.cli --brand brand_a --role sales "Prep my briefing."   # JSONL audit, offline
```

---

## 6. Two design calls you approved
- **Audit is not client-readable** (`allow read: if false`) — operator evidence shown via
  the Admin console, not a user-facing collection.
- **Audit-write failure warns, doesn't abort** — a failed write prints `[audit] WARN` to
  stderr (never silently swallowed) but the brief still completes.

## 7. Where the build stands
`main` now carries Day 1 (Phases 0–4) + Firebase **F0–F5 complete**: seeded identity,
tiered migration, 78→80-assertion rules, Cloud Functions tool surface, and the Firestore
audit sink with the live console walkthrough. **The Firebase upgrade path (PRD §17) is
done.** Nothing left in the Firebase track.
