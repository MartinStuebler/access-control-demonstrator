// Migrate the three synthetic brands into tiered Firestore collections, against the
// emulator. Tag-driven and fail-closed (see tiering.js). Idempotent: the doc id is the
// brand, and set() overwrites, so re-running produces the same two docs per brand with
// no duplication and no stale fields.

const { initEmulatorAdmin } = require("../lib/emulator");
const { getFirestore } = require("firebase-admin/firestore");
const { OPERATIONAL, ECONOMIC, listBrandIds, readBrand, splitBrand } = require("./tiering");

const { firestoreHost } = initEmulatorAdmin();
const db = getFirestore();

(async () => {
  const brands = listBrandIds();
  console.log(`Migrating ${brands.length} brands into tiered collections on ${firestoreHost}\n`);
  for (const brandId of brands) {
    const { brand, docs } = splitBrand(readBrand(brandId));
    await db.collection(OPERATIONAL).doc(brand).set(docs[OPERATIONAL]);
    await db.collection(ECONOMIC).doc(brand).set(docs[ECONOMIC]);
    const op = Object.keys(docs[OPERATIONAL].contract_terms).length;
    const ec = Object.keys(docs[ECONOMIC].contract_terms).length;
    console.log(`  ${brand}: ${OPERATIONAL}/${brand} (operational terms=${op})  +  ${ECONOMIC}/${brand} (economic terms=${ec})`);
  }
  console.log(`\nDone. Re-running is safe (deterministic doc ids, set() overwrites).`);
  process.exit(0);
})().catch((e) => { console.error(e); process.exit(1); });
