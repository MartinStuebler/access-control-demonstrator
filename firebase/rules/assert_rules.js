// Exhaustive security-rules assertion suite (runs against the Firestore emulator).
//
// Asserts every (role, brand, tier) read combination — allows AND denies — plus the
// cross-brand block, cross-tier block, unauthenticated, no-claims, unknown-role
// (fail-closed), client-write denials, and (F5) the audit collection being closed to
// every client write AND delete. The rules under test are the REAL firestore.rules file.
// Self-contained: seeds its own docs with rules disabled, so it does not depend on F2's
// migration having run. Prints the full matrix; exits non-zero on any miss. 80 assertions.

const fs = require("fs");
const path = require("path");
const {
  initializeTestEnvironment,
  assertSucceeds,
  assertFails,
} = require("@firebase/rules-unit-testing");
const { doc, getDoc, setDoc, deleteDoc } = require("firebase/firestore");

// Isolated project namespace: rules-unit-testing seeds its own throwaway docs with rules
// disabled. Using a SEPARATE project id keeps those seeds out of the real
// `demo-access-control` datastore, so running this suite never clobbers the migrated
// account docs the agent + verifiers read. (The emulator multiplexes projects by id.)
const PROJECT = "demo-rules-test";
const HOST = "127.0.0.1";
const PORT = 8080;

const ROLES = ["sales", "legal", "power_user"];
const BRANDS = ["brand_a", "brand_b", "brand_c"];
const TIERS = { operational: "accounts_operational", economic: "accounts_economic" };

// The rule, expressed once in plain code, to derive expectations.
function expectAllow(tokenBrand, role, tier, targetBrand) {
  if (tokenBrand !== targetBrand) return false;             // BRAND gate
  if (tier === "operational") return ROLES.includes(role);  // any valid role
  return role === "legal" || role === "power_user";         // economic tier
}

let pass = 0, fail = 0;
const lines = [];
function record(label, ok) {
  ok ? pass++ : fail++;
  lines.push(`  [${ok ? "PASS" : "FAIL"}] ${label}`);
}

async function expectRead(db, label, tier, targetBrand, shouldAllow) {
  const ref = doc(db, TIERS[tier], targetBrand);
  let ok = true;
  try {
    await (shouldAllow ? assertSucceeds : assertFails)(getDoc(ref));
  } catch (_) {
    ok = false;
  }
  record(`${label} read ${TIERS[tier]}/${targetBrand} -> ${shouldAllow ? "ALLOW" : "DENY"}`, ok);
}

async function expectWriteDenied(db, label, tier, targetBrand) {
  const ref = doc(db, TIERS[tier], targetBrand);
  let ok = true;
  try {
    await assertFails(setDoc(ref, { tampered: true }));
  } catch (_) {
    ok = false;
  }
  record(`${label} write ${TIERS[tier]}/${targetBrand} -> DENY`, ok);
}

(async () => {
  const rules = fs.readFileSync(path.join(__dirname, "..", "firestore.rules"), "utf8");
  const env = await initializeTestEnvironment({
    projectId: PROJECT,
    firestore: { host: HOST, port: PORT, rules },
  });

  // Seed one doc per (tier, brand) with rules disabled so reads have a target.
  await env.withSecurityRulesDisabled(async (ctx) => {
    const db = ctx.firestore();
    for (const brand of BRANDS) {
      for (const col of Object.values(TIERS)) {
        await setDoc(doc(db, col, brand), { brand_id: brand, _seed: true });
      }
    }
  });

  console.log("SECURITY-RULES ASSERTION MATRIX  (Firestore emulator)");
  console.log("=".repeat(74));

  // (1) + (2): authenticated reads — 9 principals x 6 targets = 54.
  lines.push("\n-- authenticated reads: every (role, brand) x (tier, target brand) --");
  for (const brand of BRANDS) {
    for (const role of ROLES) {
      const db = env.authenticatedContext(`${role}-${brand}`, { brand, role }).firestore();
      for (const tier of Object.keys(TIERS)) {
        for (const target of BRANDS) {
          await expectRead(db, `[${role}@${brand}]`, tier, target, expectAllow(brand, role, tier, target));
        }
      }
    }
  }

  // (3) unauthenticated reads — all 6 docs deny.
  lines.push("\n-- unauthenticated: denied at every doc --");
  {
    const db = env.unauthenticatedContext().firestore();
    for (const tier of Object.keys(TIERS))
      for (const target of BRANDS)
        await expectRead(db, "[unauth]", tier, target, false);
  }

  // (4) authenticated but NO brand/role claim — all 6 docs deny (F1 tie-in).
  lines.push("\n-- no-claims token: denied at every doc (no default identity) --");
  {
    const db = env.authenticatedContext("noclaims", {}).firestore();
    for (const tier of Object.keys(TIERS))
      for (const target of BRANDS)
        await expectRead(db, "[no-claims]", tier, target, false);
  }

  // (5) brand matches but UNKNOWN/garbage role — denied at both tiers (fail-closed).
  lines.push("\n-- unknown role (brand matches): fail-closed at both tiers --");
  for (const brand of BRANDS) {
    const db = env.authenticatedContext(`intruder-${brand}`, { brand, role: "intruder" }).firestore();
    for (const tier of Object.keys(TIERS))
      await expectRead(db, `[intruder@${brand}]`, tier, brand, false);
  }

  // (6) client writes — denied everywhere (even with a valid token).
  lines.push("\n-- client writes: denied at every doc (Admin path bypasses rules) --");
  {
    const db = env.authenticatedContext("legal-brand_a", { brand: "brand_a", role: "legal" }).firestore();
    for (const tier of Object.keys(TIERS))
      for (const target of BRANDS)
        await expectWriteDenied(db, "[legal@brand_a]", tier, target);
  }

  // (7) F5 — the audit collection is closed to every CLIENT write AND delete. A fully
  // valid token still cannot append a forged line or erase one; only the Admin-path
  // log_audit Function (which bypasses rules) can write. This is what makes it evidence.
  lines.push("\n-- audit collection: client write + delete both denied (append-only via Admin) --");
  {
    const db = env.authenticatedContext("legal-brand_a", { brand: "brand_a", role: "legal" }).firestore();
    const ref = doc(db, "audit", "forged_entry");
    let okW = true;
    try { await assertFails(setDoc(ref, { event: "forged", brand: "brand_b" })); } catch (_) { okW = false; }
    record("[legal@brand_a] write audit/forged_entry -> DENY", okW);
    let okD = true;
    try { await assertFails(deleteDoc(ref)); } catch (_) { okD = false; }
    record("[legal@brand_a] delete audit/forged_entry -> DENY", okD);
  }

  console.log(lines.join("\n"));
  console.log("\n" + "=".repeat(74));
  console.log(`RESULT: ${pass}/${pass + fail} assertions passed${fail ? `  (${fail} FAILED)` : ""}`);

  await env.cleanup();
  process.exit(fail ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
