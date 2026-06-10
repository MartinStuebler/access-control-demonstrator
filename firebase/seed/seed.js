// Seed the six synthetic accounts and set their brand/role as CUSTOM CLAIMS, via the
// privileged Admin SDK, against the Auth emulator. Idempotent: safe to re-run.
//
// Custom claims are written ONLY here (setCustomUserClaims). There is no client API
// that can write them — that is the unforgeable-binding property this phase exists for.

const { initEmulatorAdmin } = require("../lib/emulator");
const { getAuth } = require("firebase-admin/auth");
const { ACCOUNTS, SHARED_PASSWORD } = require("./accounts");

const { authHost: host } = initEmulatorAdmin();
const auth = getAuth();

async function ensureUser(email, password) {
  try {
    return await auth.getUserByEmail(email); // already seeded -> reuse (idempotent)
  } catch (e) {
    if (e.code === "auth/user-not-found") {
      return await auth.createUser({ email, password });
    }
    throw e;
  }
}

(async () => {
  console.log(`Seeding ${ACCOUNTS.length} accounts against ${host}\n`);
  for (const acct of ACCOUNTS) {
    const user = await ensureUser(acct.email, SHARED_PASSWORD);
    // The one and only place a custom claim is written — privileged, server-side.
    await auth.setCustomUserClaims(user.uid, { brand: acct.brand, role: acct.role });
    console.log(`  ${acct.email.padEnd(20)} -> brand=${acct.brand}  role=${acct.role}  (uid ${user.uid})`);
  }
  console.log(`\nDone. ${ACCOUNTS.length} accounts seeded. Re-running is safe (idempotent).`);
  process.exit(0);
})().catch((e) => { console.error(e); process.exit(1); });
