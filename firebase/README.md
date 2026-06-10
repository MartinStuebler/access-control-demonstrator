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

## Files

| File | Purpose |
|---|---|
| `firebase.json` | Emulator config (Auth, Firestore, UI). No Functions, no Hosting. |
| `.firebaserc` | `default → demo-access-control` (offline-only project id) |
| `firestore.rules` | F0 placeholder, deny-all. Real tiered rules are F3. |
| `firestore.indexes.json` | Empty — no composite indexes yet. |
| `package.json` | Local `firebase-tools` toolchain, scoped to this folder. |
