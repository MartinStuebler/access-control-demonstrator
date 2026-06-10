// Reconcile the migrated tiers against the source: per brand, the union of the two
// tiers must exactly reconstruct the source contract fields (nothing lost), with no
// field in both tiers (nothing duplicated), each field in the tier its OWN tag
// dictates, stored with the same body. Then confirm canary placement explicitly.

const { initEmulatorAdmin } = require("../lib/emulator");
const { getFirestore } = require("firebase-admin/firestore");
const { OPERATIONAL, ECONOMIC, SECTIONS, listBrandIds, readBrand } = require("./tiering");

const { firestoreHost } = initEmulatorAdmin();
const db = getFirestore();

const getDoc = async (col, id) => (await db.collection(col).doc(id).get()).data() || {};

(async () => {
  let failures = 0;

  console.log(`MIGRATION RECONCILIATION  (Firestore emulator ${firestoreHost})`);
  console.log("=".repeat(82));
  console.log("brand     source  operational  economic   union==source  disjoint  bodies+tiers");
  console.log("-".repeat(82));

  for (const brandId of listBrandIds()) {
    const src = readBrand(brandId);
    const srcTerms = Object.keys(src.contract_terms || {});
    const opDoc = await getDoc(OPERATIONAL, brandId);
    const ecDoc = await getDoc(ECONOMIC, brandId);
    const opTerms = Object.keys(opDoc.contract_terms || {});
    const ecTerms = Object.keys(ecDoc.contract_terms || {});

    const union = new Set([...opTerms, ...ecTerms]);
    const unionEqualsSource = union.size === srcTerms.length && srcTerms.every((t) => union.has(t));
    const disjoint = opTerms.filter((t) => ecTerms.includes(t)).length === 0;

    // Each source term is in the tier its visibility dictates, with an identical body.
    let faithful = true;
    for (const t of srcTerms) {
      const vis = src.contract_terms[t].visibility;
      const doc = vis === "economic" ? ecDoc : opDoc;
      const stored = doc.contract_terms ? doc.contract_terms[t] : undefined;
      if (!stored || JSON.stringify(stored) !== JSON.stringify(src.contract_terms[t])) faithful = false;
    }
    // Sections: present in operational, absent from economic.
    const sectionsOk = SECTIONS.every(
      (s) => src[s] === undefined || (opDoc[s] !== undefined && ecDoc[s] === undefined)
    );

    const ok = unionEqualsSource && disjoint && faithful && sectionsOk;
    if (!ok) failures++;
    console.log(
      `${brandId}   ${String(srcTerms.length).padStart(4)}   ${String(opTerms.length).padStart(9)}  ${String(ecTerms.length).padStart(8)}` +
      `   ${String(unionEqualsSource).padStart(11)}  ${String(disjoint).padStart(8)}  ${(faithful && sectionsOk) ? "ok" : "FAIL"}` +
      `${ok ? "" : "   <-- FAIL"}`
    );
  }

  console.log("\nCANARY PLACEMENT (exclusivity tier is tag-driven, not name-driven)");
  console.log("=".repeat(82));
  for (const brandId of listBrandIds()) {
    const src = readBrand(brandId);
    if (!src.contract_terms || !src.contract_terms.exclusivity) continue;
    const vis = src.contract_terms.exclusivity.visibility;
    const inOp = !!(await getDoc(OPERATIONAL, brandId)).contract_terms?.exclusivity;
    const inEc = !!(await getDoc(ECONOMIC, brandId)).contract_terms?.exclusivity;
    const ok = vis === "economic" ? (inEc && !inOp) : (inOp && !inEc);
    if (!ok) failures++;
    const note = brandId === "brand_a" ? " (Noir Profond terms)"
               : brandId === "brand_b" ? " (Sable Clair terms)" : "";
    console.log(`  [${ok ? "PASS" : "FAIL"}] ${brandId} exclusivity${note}: tag=${vis} -> ${inEc ? ECONOMIC : OPERATIONAL}`);
  }

  console.log("\n" + "=".repeat(82));
  console.log(failures ? `RESULT: ${failures} check(s) FAILED` : "RESULT: split is lossless, non-overlapping, and tag-faithful");
  process.exit(failures ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
