# Firebase (Day 2) — F0: emulator setup

This folder holds the Firebase upgrade path (PRD §17). It is **additive and isolated**:
nothing here touches the Day 1 build (`src/`, `Demo data/`, the Python tests). The
local CLI demonstrator remains the reliable baseline and the fallback demo.

**F0 is setup only** — Auth + Firestore running on the local Emulator Suite. Identity,
data migration, security rules, Functions, and the audit collection are F1–F5.

## What runs (entirely local, no cloud)

| Emulator | Port | Notes |
|---|---|---|
| Authentication | 9099 | Email/password sign-in (seeded accounts come in F1) |
| Firestore | 8080 | Tiered collections come in F2; rules in F3 |
| Emulator UI | 4000 | Browser dashboard for Auth + Firestore |

**No real cloud project, no login, no billing.** The project id in `.firebaserc` is
`demo-access-control`. The Firebase emulator treats any `demo-` project as
**offline-only**: it never connects to production and needs no `firebase login`, no
real project, and no Blaze plan. F0 runs fully on the emulator by construction.

## Prerequisites

- **Node** (for the Firebase CLI + Auth emulator) — installed locally in this folder.
- **A JDK** (the Firestore emulator is a Java process). Installed here via Homebrew's
  `openjdk` formula, which is keg-only, so `java` is **not** on the default `PATH`.
  Prepend it before starting the emulator:

  ```bash
  export PATH="/opt/homebrew/opt/openjdk/bin:$PATH"
  java -version   # should print openjdk
  ```

## Start it

```bash
cd firebase
npm install                                   # one-time: installs firebase-tools locally
export PATH="/opt/homebrew/opt/openjdk/bin:$PATH"   # so the Firestore emulator finds Java
npm run emulators                             # firebase emulators:start
```

The CLI resolves `firebase.json` from the working directory, so the emulator is
started from inside `firebase/`. That `cd` is the only cost of keeping Firebase out of
the repo root and fully isolated from Day 1.

Open the dashboard at <http://localhost:4000>. Stop with `Ctrl-C`.

## Seeded identity (F1)

Six synthetic accounts, created by the seed script only — **no self-registration**.
Each carries its `brand` and `role` as **custom claims** on the signed ID token, set
server-side via the Admin SDK. The client can never set or alter a claim.

| Account | brand | role |
|---|---|---|
| `sales@lirelle.demo` | `brand_a` (Maison Lirelle) | `sales` |
| `legal@lirelle.demo` | `brand_a` | `legal` |
| `power@lirelle.demo` | `brand_a` | `power_user` |
| `sales@solene.demo`  | `brand_b` (Atelier Solene) | `sales` |
| `legal@solene.demo`  | `brand_b` | `legal` |
| `power@solene.demo`  | `brand_b` | `power_user` |

Shared password for all six (throwaway emulator identities): **`demo-password`**.

### Run the seed + verification

With the emulator running (see above), in a second terminal:

```bash
cd firebase
npm run seed      # idempotent: creates the six accounts and sets brand/role claims
npm run verify    # signs in as each, decodes the signed ID token, asserts the claims
```

`verify` also runs the **negative** check: it self-registers an account through the
client sign-up endpoint *while trying to smuggle `brand`/`role`*, and shows the
resulting token has neither — proving claims come from the Admin seed, never the
client. Both scripts are emulator-only by construction (they refuse to run unless
`FIREBASE_AUTH_EMULATOR_HOST` points at a local emulator).

### Why the client cannot forge identity

- Custom claims are written **only** by the privileged Admin SDK
  (`setCustomUserClaims`), in `seed/seed.js`. Firebase client SDKs expose no method to
  set a claim — they can only read it from the decoded token.
- In production the Admin SDK requires a service-account key the client never holds,
  and the claim is baked into the token Google signs. The emulator simulates this; the
  carry-over property is that **no client path writes a claim**.

### Identity model — what stays OFF (carry-over guardrail)

Logins are identifier strings, **not real mailboxes**, so:

- **Email/password sign-in only.**
- **Do NOT enable** email verification, email-link (passwordless) sign-in, or
  password-reset — each would try to mail an address that doesn't exist and fail.

## Tiered Firestore data (F2)

The Day 1 **field** boundary becomes a Firestore **document** boundary, because rules
allow a whole document or none. Each brand is split into two collections, document id =
brand:

| Collection | Holds | Visible to |
|---|---|---|
| `accounts_operational/{brand}` | `profile` + `orders` + `open_issues` + `last_contact` + `notes`, plus the **operational** fields of `contract_terms` | sales, legal, power_user |
| `accounts_economic/{brand}` | only the **economic** fields of `contract_terms` | legal, power_user |

The two tiers map exactly to the Day 1 `can_see` boundary (sales = public+operational;
legal/power_user add economic). A `power_user` reads both tiers of its bound brand,
never another brand — F3's rules enforce that at the database.

> **Naming note:** PRD §17 sketches `contracts_*`; this uses `accounts_*` because the
> operational tier holds the whole account picture (orders, notes, …), not just
> contract terms. `brand_id`/`brand_name` are carried in both docs as identifiers;
> `_schema_note` (a developer comment) is excluded.

**Tag-driven, fail-closed.** The tier of every unit is read from its own `visibility`
tag (`migrate/tiering.js`), never a hardcoded field list — brand_c's `exclusivity`
(tagged operational) lands in the operational tier, while brand_a/brand_b's (economic)
land in the economic tier. A field with a missing or unknown tag aborts the migration
rather than silently landing in the more-visible tier.

### Run the migration + reconciliation

With the emulator running:

```bash
cd firebase
npm run migrate          # idempotent: writes both tiers per brand into Firestore
npm run migrate:verify   # reconciles: union of tiers == source, disjoint, tag-faithful
```

`migrate:verify` prints a per-brand field-count table (source vs operational vs
economic) and the canary placement, and exits non-zero on any mismatch. Both scripts
are emulator-only by construction.

> A benign `MetadataLookupWarning` may print: the Admin SDK probes for Google
> credentials it doesn't need against the emulator. All operations succeed; it can be
> ignored.

## Security rules (F3)

`firestore.rules` enforces the brand and tier boundary **inside the database**, on
every read, before any data is returned — the agent, the Functions, or a raw client
with the URL all face the same gate. This is the Day 1 `decide()` logic moved below the
application.

In plain language:

- **Brand gate (tenancy):** the token's `brand` claim must equal the brand in the
  document path (`accounts_*/{brand}`). Any other brand is denied — the database-level
  cross-brand block.
- **Tier gate (access control):** `accounts_operational` allows `sales`, `legal`,
  `power_user`; `accounts_economic` allows only `legal`, `power_user`. Sales reading
  economic is denied.
- **Fail-closed:** a token with no `brand`/`role` claim, or an unknown/garbage role, is
  denied at both tiers (the role allowlist admits nothing else). Unauthenticated reads
  are denied.
- **No client writes:** every write is `if false`; data is written only by the
  seed/migration Admin SDK, which bypasses rules. Default-deny everywhere else.

### Run the assertion suite

With the emulator running:

```bash
cd firebase
npm run rules:test
```

Uses `@firebase/rules-unit-testing` against the real `firestore.rules`. It is
self-contained (seeds its own docs with rules disabled, so it does not need the F2
migration to have run) and asserts **every** combination — exhaustively:

| Category | Cases |
|---|---|
| Authenticated reads: every (role × brand) principal × (tier × target brand) | 54 |
| Unauthenticated reads denied | 6 |
| No-claims token denied (F1 tie-in) | 6 |
| Unknown/garbage role denied at both tiers (fail-closed) | 6 |
| Client writes denied | 6 |
| **Total** | **78 rules assertions, all passing** |

15 allows, 63 denies — the denials are the proof. The suite prints the full matrix and
exits non-zero on any miss. (Six expected `PERMISSION_DENIED` lines are logged by the
Firestore client during the asserted write-denials — they are expected, not failures.)

## Cloud Functions as the tool surface (F4)

The agent's three read tools become **HTTPS callable Cloud Functions** (`functions/index.js`)
on the Functions emulator. This is the **application layer** of the two-layer defense; the
F3 rules sit underneath it. The agent holds **no Firestore client** — the Functions are its
only path to data.

Each function does the same three things:

1. **Verifies the signed ID token** (`onCall` verifies it; we then assert the claims are
   present and the role is known — fail-closed).
2. **Builds the Principal from the verified token claims only** — `brand`/`role` come from
   `request.auth.token`, **never** from `request.data`. A client that smuggles a different
   `brand` in the call body is ignored; identity is what Google signed.
3. **Reads only the tiers that token entitles** (via the Admin SDK): operational always;
   economic only for `legal`/`power_user`.

| Function | sales | legal / power_user |
|---|---|---|
| `get_account_overview` | operational sections (profile, orders, issues, last contact) | same |
| `get_contract_terms` | operational fields served; **economic withheld (named)** | operational **+** economic served |
| `search_account_notes` | notes (operational tier), substring match | same |

`draft_briefing` and `share_briefing` are **not** Functions. `draft_briefing` composes the
brief client-side from the *served* output of the two read Functions — it only ever touches
already-filtered data (the Day 1 guarantee), and the brief is rendered by the **same**
formatter both backends call (`src/tools.py: compose_briefing`), so it is byte-identical to
local mode. `share_briefing` stays the non-sending `pending_human_approval` stub.

**Naming withheld fields without reading the economic tier.** Sales must name the withheld
economic fields but must not read the economic doc. So the migration writes the economic
field **names** (not values) into the operational doc as `contract_field_index` (source
order, each tagged with its tier). Sales reads only the operational doc, serves operational
fields, and names the economic ones as withheld — their **values never leave the economic
tier**. (Audit-to-Firestore is **F5**, below.)

### The two layers, both refusing

- **Layer 2 (Functions):** the function derives `brand` from the token, so a `brand_b`
  caller can never reach `brand_a` through it — there is no brand parameter, and a smuggled
  one is ignored.
- **Layer 1 (rules, F3):** even a raw client talking straight to Firestore with a `brand_b`
  token is denied `brand_a` at the database (`403`). The model sits outside both.

### Run it on the emulator

```bash
cd firebase
export PATH="/opt/homebrew/opt/openjdk/bin:$PATH"   # Firestore emulator needs Java
npm install --prefix functions                       # one-time: functions deps
npm run emulators                                    # Auth + Firestore + Functions
# in a second terminal:
cd firebase && npm run seed && npm run migrate        # seeded identities + tiered data
python3 verify_f4.py                                  # end-to-end matrix (see below)
```

The agent itself runs in Firebase mode from the repo root:

```bash
python -m src.cli --backend firebase --brand brand_a --role sales "Prep my briefing."
```

### Verification (`verify_f4.py`)

Exercises the **real** path the agent uses (sign in to the Auth emulator → call the
Functions with the token) and asserts the whole matrix:

| Category | Checks |
|---|---|
| Per-role served vs withheld through `get_contract_terms` (sales operational-only & valueless; legal/power_user economic too) | 6 |
| Cross-brand refused at **both** layers (L2 Function ignores smuggled brand; L1 rules `403`, with a same-brand `200` control) | 3 |
| Fail-closed identities refused at the Function: no-claims, unauthenticated, unknown-role | 5 |
| `draft_briefing` **byte-identical** firebase vs local, every principal | 6 |
| **Total** | **20 checks, all passing** |

## Audit to Firestore (F5)

The Day 1 audit log (`src/audit.py`) had one sink: append-only JSONL. F5 gives it a
**second sink** — a Firestore `audit` collection — selected by the active backend. **One
audit interface, two sinks**: local mode still writes JSONL (unchanged, the offline
baseline); firebase mode writes to Firestore. The events and their fields are assembled
once, in `AuditLog`; only the destination differs. Same shapes either way: `run_start`,
`tool_call` (with `served`/`withheld`), `run_end`, `cross_brand_block` (with
`initiated_by`).

**The integrity property: the trail cannot be forged or erased by a client.** An audit
log is only evidence if a client can neither add a fake line nor delete a real one.

- **Writes go through the Admin path, never a client.** The Python backend signs in as an
  ordinary seeded user — it holds only client privileges, and the F3 rules deny *every*
  client write to `audit`. The only way to append is the new **`log_audit` callable
  Function** (`functions/index.js`), which writes with the Admin SDK (bypassing rules),
  the same discipline as seed/migrate and the read tools.
- **Identity is server-authoritative.** `log_audit` re-derives `brand`/`role` from the
  **verified token** and stamps `ts` from the server clock — the client-sent values for
  those three keys are dropped. A caller cannot attribute a line to another brand/role or
  backdate it. (The event payload — `tool`, `served`, `withheld`, … — is the caller's
  report of what it did.) Fail-closed: unauthenticated / no-claims / unknown-role callers
  cannot write a line at all.
- **Append-only.** `log_audit` only ever adds a document; there is **no** update or delete
  Function anywhere, and the rules deny client update/delete. Once written, an entry is
  immutable through every path.

The rule that makes it tamper-evident (`firestore.rules`):

```
match /audit/{entry} {
  allow read:  if false;   // evidence: shown via the Admin console, not client-readable
  allow write: if false;   // create, update, AND delete denied for every client
}
```

In Firestore rules, `write` folds in create, update, and delete — so this one line denies
a client write **and** a client delete. The `assert_rules.js` suite asserts both
explicitly (the suite now totals **80** assertions).

### Run a firebase-mode run and see its trail

```bash
# emulator running, seeded + migrated (see above):
python -m src.cli --backend firebase --brand brand_a --role sales \
  --cross-brand-probe brand_b "Prep my briefing."
```

The terminal footer prints the `run_id`; open the `audit` collection in the Emulator UI
(<http://localhost:4000> → Firestore) to see `run_start`, the `tool_call`s (operational
field names served, economic field names withheld — **names, no values**), `run_end`, and
the operator-initiated `cross_brand_block`, all scoped to `brand_a`. See `../DEMO.md` for
the full console walkthrough.

> A failed audit write prints a loud `[audit] WARN` to stderr (an evidence gap is never
> swallowed) but does not crash the brief — the run still completes.

### Verification (`verify_f5.py`)

Drives the real audit path (`AuditLog → FirestoreAuditSink → log_audit → Firestore`),
reads the collection back via the emulator owner endpoint, and asserts:

| Category | Checks |
|---|---|
| A run writes `run_start` / `tool_call` (served+withheld) / `run_end` to Firestore | 3 |
| `get_contract_terms` records operational names served, economic names withheld (no values) | 2 |
| Every line scoped to the bound brand; nothing from another brand | 1 |
| `cross_brand_block` present, `initiated_by=operator_probe` (not the model) | 1 |
| Identity server-authoritative: a forged `brand_b`/`legal`/1999-`ts` stored as token's `brand_a`/`sales`/server-time | 3 |
| Authenticated **ordinary seeded user** denied client write + delete + read on `audit` (`403`) | 3 |
| **Total** | **13 checks, all passing** |

## Files

| File | Purpose |
|---|---|
| `firebase.json` | Emulator config (Auth, Firestore, **Functions**, UI). No Hosting. |
| `.firebaserc` | `default → demo-access-control` (offline-only project id) |
| `firestore.rules` | Tiered brand + tier rules (F3) + **append-only `audit` block (F5)**. |
| `firestore.indexes.json` | Empty — no composite indexes yet. |
| `package.json` | Local `firebase-tools` toolchain, scoped to this folder. |
| `functions/index.js` | F4 read tools + **F5 `log_audit`** (Admin-path audit sink). |
| `functions/package.json` | Functions codebase deps (`firebase-functions`, `firebase-admin`). |
| `migrate/tiering.js` | F2 split + F4 `contract_field_index` (economic field **names**, no values). |
| `rules/assert_rules.js` | Exhaustive rules suite (80), isolated project so it never clobbers demo data. |
| `verify_f4.py` | F4 end-to-end matrix (20 checks) against the emulator. |
| `verify_f5.py` | F5 audit-to-Firestore matrix (13 checks): trail, scope, integrity, deny proofs. |
| `../DEMO.md` | Console-walkthrough script for the live closing beat. |

| File | Purpose |
|---|---|
| `firebase.json` | Emulator config (Auth, Firestore, **Functions**, UI). No Hosting. |
| `.firebaserc` | `default → demo-access-control` (offline-only project id) |
| `firestore.rules` | Tiered brand + tier rules (F3). |
| `firestore.indexes.json` | Empty — no composite indexes yet. |
| `package.json` | Local `firebase-tools` toolchain, scoped to this folder. |
| `functions/index.js` | F4 — the three callable read tools (verify token, read entitled tiers). |
| `functions/package.json` | Functions codebase deps (`firebase-functions`, `firebase-admin`). |
| `migrate/tiering.js` | F2 split + F4 `contract_field_index` (economic field **names**, no values). |
| `verify_f4.py` | F4 end-to-end matrix (20 checks) against the emulator. |
