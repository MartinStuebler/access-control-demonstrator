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

// F5 — the audit sink as an Admin-path callable Function.
//
// The audit log is evidence only if a client cannot forge or erase it. A client
// (the Python backend signs in as an ordinary seeded user) holds only client
// privileges, and the F3 rules deny EVERY client write to `audit` — so the only way
// to append is through this Function, which writes with the Admin SDK (bypassing
// rules), the same discipline as seed/migrate. Two integrity guarantees:
//
//   1. IDENTITY IS SERVER-AUTHORITATIVE. `brand`/`role`/`ts` on the stored document are
//      stamped from the VERIFIED token (and the server clock), never from request.data.
//      A caller cannot attribute an audit line to another brand/role or backdate it; the
//      client-sent values for those three keys are dropped. The event payload (tool,
//      served, withheld, run_id, …) is the caller's report of what it did.
//   2. APPEND-ONLY. This Function only ever .add()s a new document. There is NO update or
//      delete Function anywhere, and the rules deny client update/delete — so once
//      written, an entry cannot be mutated or removed through any path.
//
// Fail-closed: principalFrom() rejects unauthenticated, no-claims, and unknown-role
// callers, so none of them can write a line (ties to F1 + F3).
exports.log_audit = onCall(async (request) => {
  const p = principalFrom(request);
  const record = (request.data && request.data.record) || {};
  if (typeof record.event !== "string" || !record.event) {
    throw new HttpsError("invalid-argument", "audit record needs an 'event' string.");
  }
  // Drop client-supplied identity/time; the server is authoritative for these three.
  const { ts, brand, role, ...payload } = record;
  const docData = {
    ...payload,                       // run_id, event, and event-specific fields
    brand: p.brand,                   // from the verified token, not the client
    role: p.role,                     // from the verified token, not the client
    ts: new Date().toISOString(),     // server clock, not the client's
  };
  const ref = await db.collection("audit").add(docData);
  return { ok: true, id: ref.id };
});
