// Shared Admin SDK bootstrap — EMULATOR ONLY, by construction.
//
// Points the Admin SDK at the local Auth + Firestore emulators. If either host is not
// a local emulator, we refuse to run, so any script using this can never create users,
// write claims, or write documents against a real Firebase project.

const { getApps, initializeApp } = require("firebase-admin/app");

const LOCAL = /^(127\.0\.0\.1|localhost):\d+$/;

function initEmulatorAdmin() {
  process.env.FIREBASE_AUTH_EMULATOR_HOST ||= "127.0.0.1:9099";
  process.env.FIRESTORE_EMULATOR_HOST ||= "127.0.0.1:8080";
  for (const v of ["FIREBASE_AUTH_EMULATOR_HOST", "FIRESTORE_EMULATOR_HOST"]) {
    if (!LOCAL.test(process.env[v] || "")) {
      console.error(
        `Refusing to run: ${v}='${process.env[v]}' is not a local emulator. ` +
        `These scripts are emulator-only and must never touch a real project.`
      );
      process.exit(1);
    }
  }
  if (getApps().length === 0) {
    initializeApp({ projectId: "demo-access-control" }); // demo- => offline, no creds
  }
  return {
    authHost: process.env.FIREBASE_AUTH_EMULATOR_HOST,
    firestoreHost: process.env.FIRESTORE_EMULATOR_HOST,
  };
}

module.exports = { initEmulatorAdmin };
