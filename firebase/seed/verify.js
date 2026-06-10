// Verify the binding is real and unforgeable, against the emulator:
//   1. Each seeded account, signed in, carries the expected brand/role on its SIGNED
//      ID token (decoded AND cross-checked with admin.verifyIdToken).
//   2. NEGATIVE: an account self-registered through the CLIENT sign-up endpoint — even
//      while trying to smuggle brand/role in the request — gets a token with NO claims.
//      This proves claims come from the Admin seed, never from the client or by default.

const { initEmulatorAdmin } = require("./emulator");
const { getAuth } = require("firebase-admin/auth");
const { ACCOUNTS, SHARED_PASSWORD } = require("./accounts");

const { host } = initEmulatorAdmin();
const auth = getAuth();
const API = `http://${host}/identitytoolkit.googleapis.com/v1`;

function decodeJwt(idToken) {
  const payload = idToken.split(".")[1];
  return JSON.parse(Buffer.from(payload, "base64url").toString("utf8"));
}

async function clientSignIn(email, password) {
  const res = await fetch(`${API}/accounts:signInWithPassword?key=fake-api-key`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password, returnSecureToken: true }),
  });
  if (!res.ok) throw new Error(`signIn ${email}: ${res.status} ${await res.text()}`);
  return (await res.json()).idToken;
}

async function clientSignUpSmugglingClaims(email, password) {
  // The self-registration path a user would take. We deliberately try to inject
  // brand/role — the client endpoint has no such field and ignores them.
  const res = await fetch(`${API}/accounts:signUp?key=fake-api-key`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      email, password, returnSecureToken: true,
      brand: "brand_a", role: "power_user", // smuggled — must be ignored
      customAttributes: JSON.stringify({ brand: "brand_a", role: "power_user" }),
    }),
  });
  if (!res.ok) throw new Error(`signUp: ${res.status} ${await res.text()}`);
  return await res.json(); // { idToken, localId, ... }
}

(async () => {
  let failures = 0;

  console.log(`SIGNED-TOKEN CLAIM CHECK  (emulator ${host})`);
  console.log("=".repeat(68));
  for (const acct of ACCOUNTS) {
    const idToken = await clientSignIn(acct.email, SHARED_PASSWORD);
    const decoded = decodeJwt(idToken);                       // what the token carries
    const verified = await auth.verifyIdToken(idToken); // valid signed token
    const ok = decoded.brand === acct.brand && decoded.role === acct.role
            && verified.brand === acct.brand && verified.role === acct.role;
    if (!ok) failures++;
    console.log(`  [${ok ? "PASS" : "FAIL"}] ${acct.email.padEnd(20)} token: brand=${decoded.brand}  role=${decoded.role}`);
  }

  console.log("\nNEGATIVE — a client-created account has no brand/role");
  console.log("=".repeat(68));
  const tmp = "unclaimed-temp@demo";
  try { const u = await auth.getUserByEmail(tmp); await auth.deleteUser(u.uid); } catch {}
  const signUp = await clientSignUpSmugglingClaims(tmp, SHARED_PASSWORD);
  const claims = decodeJwt(signUp.idToken);
  const noClaims = claims.brand === undefined && claims.role === undefined;
  if (!noClaims) failures++;
  console.log(`  [${noClaims ? "PASS" : "FAIL"}] ${tmp} self-registered (smuggling brand/role): token brand=${claims.brand} role=${claims.role}`);
  console.log("         the client signUp endpoint has no claim field; the smuggled values were ignored");
  await auth.deleteUser(signUp.localId); // clean up the throwaway

  console.log("\n" + "=".repeat(68));
  console.log(failures ? `RESULT: ${failures} check(s) FAILED` : "RESULT: all checks passed");
  process.exit(failures ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
