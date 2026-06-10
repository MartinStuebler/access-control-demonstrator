// Tag -> tier mapping. The Day 1 visibility tags are the source of truth; this module
// reads them and never re-decides them. Tier comes from each unit's OWN visibility tag,
// never from a hardcoded field list (proven by brand_c's `exclusivity`, tagged
// operational, landing in the operational tier).

const fs = require("fs");
const path = require("path");

// Read-only Day 1 input. We read the tags from here; we never modify it.
const ACCOUNTS_DIR = path.join(__dirname, "..", "..", "Demo data", "synth intelligence files");

const OPERATIONAL = "accounts_operational"; // public + operational (sales and up)
const ECONOMIC = "accounts_economic";       // economic (legal / power_user only)

// Section-level keys, each carrying its own `visibility` on the section object.
const SECTIONS = ["profile", "orders", "open_issues", "last_contact", "notes"];

const OPERATIONAL_VIS = new Set(["public", "operational"]);

function listBrandIds() {
  return fs.readdirSync(ACCOUNTS_DIR)
    .filter((f) => /^brand_.*\.json$/.test(f))
    .map((f) => f.replace(/\.json$/, ""))
    .sort();
}

function readBrand(brandId) {
  return JSON.parse(fs.readFileSync(path.join(ACCOUNTS_DIR, `${brandId}.json`), "utf8"));
}

// Fail closed: a missing or unknown visibility tag must NOT silently land in the more-
// visible (operational) tier. We refuse to place it at all and abort, naming the field,
// mirroring Day 1's deny-on-unknown-tag. On the real data this never fires.
function tierFor(visibility, where) {
  if (OPERATIONAL_VIS.has(visibility)) return OPERATIONAL;
  if (visibility === "economic") return ECONOMIC;
  throw new Error(
    `FAIL-CLOSED: ${where} has visibility=${JSON.stringify(visibility)}. A missing or ` +
    `unknown tag must not be placed in any visible tier. Fix the tag in the source.`
  );
}

// Split one brand's source record into the two tier documents. Original nesting is
// preserved so the union reconstructs the source exactly. brand_id/brand_name are
// identifiers carried in both docs; `_schema_note` (a developer comment) is excluded.
function splitBrand(src) {
  const brand = src.brand_id;
  const docs = {
    [OPERATIONAL]: { brand_id: brand, brand_name: src.brand_name, contract_terms: {} },
    [ECONOMIC]:    { brand_id: brand, brand_name: src.brand_name, contract_terms: {} },
  };
  for (const s of SECTIONS) {
    if (src[s] === undefined) continue;
    docs[tierFor(src[s].visibility, `${brand}.${s}`)][s] = src[s];
  }
  for (const [field, body] of Object.entries(src.contract_terms || {})) {
    docs[tierFor(body.visibility, `${brand}.contract_terms.${field}`)].contract_terms[field] = body;
  }
  return { brand, docs };
}

module.exports = { OPERATIONAL, ECONOMIC, SECTIONS, listBrandIds, readBrand, splitBrand, tierFor };
