// The six seeded synthetic identities — the single source of truth for seed + verify.
//
// Brand keys MATCH the Day 1 data (Demo data/synth intelligence files/): brand_a is
// Maison Lirelle (lirelle accounts), brand_b is Atelier Solene (solene accounts).
// Roles match entitlements.json exactly: sales | legal | power_user.
//
// These are throwaway emulator identities. The addresses are identifier strings, not
// real mailboxes, so NO email verification / email-link / password-reset is ever used.

const SHARED_PASSWORD = "demo-password"; // documented in firebase/README.md; emulator-only

const ACCOUNTS = [
  { email: "sales@lirelle.demo", brand: "brand_a", role: "sales" },
  { email: "legal@lirelle.demo", brand: "brand_a", role: "legal" },
  { email: "sales@solene.demo",  brand: "brand_b", role: "sales" },
  { email: "legal@solene.demo",  brand: "brand_b", role: "legal" },
  { email: "power@lirelle.demo", brand: "brand_a", role: "power_user" },
  { email: "power@solene.demo",  brand: "brand_b", role: "power_user" },
];

module.exports = { SHARED_PASSWORD, ACCOUNTS };
