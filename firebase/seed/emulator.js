// Shared Admin SDK bootstrap — EMULATOR ONLY, by construction.
//
// The Admin SDK is pointed at the Auth emulator via FIREBASE_AUTH_EMULATOR_HOST. If
// that host is not a local emulator, we refuse to run, so these scripts can never
// create users or write claims against a real Firebase project.

const { getApps, initializeApp } = require("firebase-admin/app");

function initEmulatorAdmin() {
  process.env.FIREBASE_AUTH_EMULATOR_HOST ||= "127.0.0.1:9099";
  const host = process.env.FIREBASE_AUTH_EMULATOR_HOST;
  if (!/^(127\.0\.0\.1|localhost):\d+$/.test(host)) {
    console.error(
      `Refusing to run: FIREBASE_AUTH_EMULATOR_HOST is '${host}', not a local emulator. ` +
      `These scripts are emulator-only and must never touch a real project.`
    );
    process.exit(1);
  }
  if (getApps().length === 0) {
    initializeApp({ projectId: "demo-access-control" }); // demo- => offline, no creds
  }
  return { host };
}

module.exports = { initEmulatorAdmin };
