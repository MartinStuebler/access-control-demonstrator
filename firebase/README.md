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

## Identity model — notes for F1 (do NOT enable these now)

F1 will seed synthetic accounts only; there is no self-registration. Logins are
identifier strings like `sales@lirelle.demo`, **not real mailboxes**. Therefore:

- **Email/password sign-in only.**
- **Do NOT enable** email verification, email-link (passwordless) sign-in, or
  password-reset flows — every one of those tries to send mail to an address that
  doesn't exist and will fail. Role and brand will be set as **custom claims** on the
  ID token via the Admin SDK (server-side), never by the client.

## Files

| File | Purpose |
|---|---|
| `firebase.json` | Emulator config (Auth, Firestore, UI). No Functions, no Hosting. |
| `.firebaserc` | `default → demo-access-control` (offline-only project id) |
| `firestore.rules` | F0 placeholder, deny-all. Real tiered rules are F3. |
| `firestore.indexes.json` | Empty — no composite indexes yet. |
| `package.json` | Local `firebase-tools` toolchain, scoped to this folder. |
