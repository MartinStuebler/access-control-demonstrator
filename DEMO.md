# Console walkthrough — the live closing beat (Firebase, emulator)

A ~5-minute live script for showing the two-layer defense and the audit evidence in the
Firebase Emulator UI. Everything is local: no cloud, no Blaze, no billing. The point of
this beat is that **live infrastructure reads as more credible than local JSON** — the
denials and the audit trail are real Firestore behavior, not a script.

## 0. Bring it up (one terminal)

```bash
cd firebase
export PATH="/opt/homebrew/opt/openjdk/bin:$PATH"   # Firestore emulator needs Java
npm run emulators                                    # Auth + Firestore + Functions + UI
# in a second terminal:
cd firebase && npm run seed && npm run migrate        # seeded identities + tiered data
```

Open the Emulator UI at <http://localhost:4000>. Keep the **Firestore** tab handy.

> If you ran `npm run rules:test` against this emulator, it uses an isolated project
> (`demo-rules-test`) and does **not** touch the demo data — no re-migrate needed.

---

## Beat 1 — a governed run, economic fields withheld (the happy path)

From the repo root:

```bash
python -m src.cli --backend firebase --brand brand_a --role sales "Prep my briefing."
```

Point out in the output:
- The brief is built from Cloud Functions (the agent holds no Firestore client).
- The five **operational** contract terms are served (term length, lead time, MOQ, …).
- The line: *"The following contract terms exist but are withheld at your access level:
  unit price, price escalator, exclusivity, margin floor, late delivery penalty."*
  Sales **names** the withheld economic fields but never sees their values — the values
  never leave the `accounts_economic` tier.

## Beat 2 — the audit collection, scoped to the brand (the evidence)

In the Emulator UI → **Firestore** → `audit` collection. Sort by `ts`. Show the run you
just executed (match the `run_id` printed in the terminal footer):

| event | what to point at |
|---|---|
| `run_start` | the run is bound to `brand=brand_a role=sales` |
| `tool_call` (`get_contract_terms`) | `served` = the 5 operational field **names**; `withheld` = the 5 economic field **names**, **no values** |
| `tool_call` (`get_account_overview`, `draft_briefing`) | operational sections only |
| `run_end` | run closed |

Every document carries `brand = brand_a` and nothing from another brand. **That uniform
scope is the proof that no cross-brand access happened.**

## Beat 3 — the cross-brand refusal, both layers (the denial)

Run the operator probe (the agent itself has no brand parameter, so a cross-brand
request can only come from the operator/eval harness):

```bash
python -m src.cli --backend firebase --brand brand_a --role sales \
  --cross-brand-probe brand_b "Prep my briefing."
```

- In the `audit` collection, a new `cross_brand_block` document appears:
  `requested_brand = brand_b`, `initiated_by = operator_probe` — honest about *who*
  triggered it ("operator probed, policy refused," never "the agent tried").
- **Layer 1 (rules), live:** show a raw cross-brand read denied at the database. In a
  terminal, with a `brand_b` token trying to read `brand_a`:

  ```bash
  # (verify_f4.py automates this; to show it by hand, sign in as sales@solene.demo and
  #  GET accounts_operational/brand_a — the emulator returns HTTP 403 PERMISSION_DENIED.)
  ```

  Or simply run `python3 firebase/verify_f4.py` and point at the two lines:
  `L1 rules: raw client read brand_b->brand_a = 403 DENIED` and the `200` same-brand
  control next to it.

## Beat 4 — the rules next to the denied read (the layer that enforced it)

In the Emulator UI → **Firestore** → **Rules** tab (or open `firebase/firestore.rules`).
Show, side by side with the denial:
- the **brand gate** (`brandMatches`) — the token's `brand` must equal the path brand;
- the **tier gate** (`roleIn`) — `accounts_economic` admits only `legal`/`power_user`;
- the **audit block** — `allow read, write: if false` on `/audit/{entry}`: a client can
  neither append a forged line nor delete one. The trail is append-only, written solely
  by the Admin-path `log_audit` Function.

**Closing line:** *"Two real layers. The Functions verify the signed token and read only
entitled tiers; the rules deny anything else at the database — even a raw client with the
URL. The model sits outside both, and every move it makes is logged to an audit trail no
client can forge or erase."*

---

## The audit integrity claim, shown live (optional)

To demonstrate that the audit log is tamper-evident, run the F5 verifier — it attempts a
client write and a client delete to `audit` **as an authenticated, ordinary seeded user**
(`sales@lirelle.demo`), and both return `403`:

```bash
python3 firebase/verify_f5.py
```

Point at:
- `client WRITE to audit (logged-in sales user) -> 403 DENIED`
- `client DELETE of an audit doc (logged-in sales user) -> 403 DENIED`
- `client-sent brand=brand_b stored as token's brand_a (overwritten)` — identity on each
  line is stamped server-side from the verified token, not from anything the client sends.
