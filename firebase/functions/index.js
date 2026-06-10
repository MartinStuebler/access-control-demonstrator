// F4 — the agent's read tools as HTTPS callable Cloud Functions (emulator).
//
// This is the APPLICATION layer of the two-layer defense. Each function:
//   1. verifies the caller's signed ID token (onCall does this; we then assert the
//      claims are present and the role is known — fail-closed, ties to F1 + F3),
//   2. builds the Principal from the VERIFIED token claims only — never from anything
//      the client sends in request.data (a smuggled `brand` is ignored), and
//   3. reads ONLY the tiered collections that token entitles, via the Admin SDK.
//
// The agent holds no Firestore client; these functions are its sole path to data. Even
// if one had a bug and reached for the wrong tier through a CLIENT path, the F3 rules
// deny it at the database. The model sits outside both layers.

const { onCall, HttpsError } = require("firebase-functions/v2/https");
const { getApps, initializeApp } = require("firebase-admin/app");
const { getFirestore } = require("firebase-admin/firestore");

if (getApps().length === 0) initializeApp({ projectId: "demo-access-control" });
const db = getFirestore();

const OPERATIONAL = "accounts_operational";
const ECONOMIC = "accounts_economic";

// Tier entitlement by role — the same boundary as entitlements.json and the F3 rules,
// expressed once here. An unknown role maps to nothing and is denied below.
const ROLE_TIERS = {
  sales: ["operational"],
  legal: ["operational", "economic"],
  power_user: ["operational", "economic"],
};

// Build the Principal from the verified token, fail-closed. Identity is read from
// request.auth.token (what Google signed), NEVER from request.data (what the client typed).
function principalFrom(request) {
  const auth = request.auth;
  if (!auth) {
    throw new HttpsError("unauthenticated", "No verified ID token on the call; denied.");
  }
  const brand = auth.token.brand;
  const role = auth.token.role;
  if (typeof brand !== "string" || typeof role !== "string") {
    throw new HttpsError(
      "permission-denied",
      "Token carries no brand/role claim; denied (fail-closed, ties to F1)."
    );
  }
  if (!ROLE_TIERS[role]) {
    throw new HttpsError(
      "permission-denied",
      `Unknown role '${role}' is in no entitlement; denied (fail-closed, ties to F3).`
    );
  }
  return { brand, role, tiers: ROLE_TIERS[role] };
}

async function readTier(tier, brand) {
  const col = tier === "economic" ? ECONOMIC : OPERATIONAL;
  const snap = await db.collection(col).doc(brand).get();
  return snap.exists ? snap.data() : null;
}

// A section's `visibility` tag is migration metadata; the tool returns data, not tags.
function stripVisibility(section) {
  const { visibility, ...rest } = section;
  return rest;
}

// Operational-tier sections that make up the account overview (notes excluded, as in
// Day 1's _gather_overview). All are operational/public, so every valid role sees them.
const OVERVIEW_SECTIONS = ["profile", "orders", "open_issues", "last_contact"];

exports.get_account_overview = onCall(async (request) => {
  const p = principalFrom(request);
  const op = (await readTier("operational", p.brand)) || {};
  const served = {};
  const withheld = [];
  for (const name of OVERVIEW_SECTIONS) {
    if (op[name] !== undefined) served[name] = stripVisibility(op[name]);
  }
  return { brand: p.brand, brand_name: op.brand_name || p.brand, served, withheld };
});

exports.get_contract_terms = onCall(async (request) => {
  const p = principalFrom(request);
  const op = (await readTier("operational", p.brand)) || {};
  const economicAllowed = p.tiers.includes("economic");
  // Read the economic doc ONLY if entitled. Sales never reads it — its field names come
  // from the operational doc's contract_field_index, its values never leave the tier.
  const ec = economicAllowed ? (await readTier("economic", p.brand)) || {} : null;

  const index = op.contract_field_index || [];
  const served = {};
  const withheld = [];
  for (const { name, tier } of index) {
    if (tier === "operational") {
      served[name] = op.contract_terms?.[name]?.value;
    } else if (economicAllowed) {
      served[name] = ec.contract_terms?.[name]?.value;
    } else {
      withheld.push({
        field: name,
        code: "withheld",
        reason: `economic data is withheld at the ${p.role} access level`,
      });
    }
  }
  return { brand: p.brand, served, withheld };
});

exports.search_account_notes = onCall(async (request) => {
  const p = principalFrom(request);
  const op = (await readTier("operational", p.brand)) || {};
  const notes = op.notes;
  if (!notes) return { brand: p.brand, matches: [], withheld: [] };
  const q = String((request.data && request.data.query) || "").toLowerCase();
  // Notes are returned as DATA to quote, never executed — same as Day 1. Any injection
  // text inside a note is inert because no other brand's data is reachable anyway.
  const matches = (notes.items || [])
    .filter((it) => String(it.text || "").toLowerCase().includes(q))
    .map((it) => ({ id: it.id, text: it.text }));
  return { brand: p.brand, matches, withheld: [] };
});
