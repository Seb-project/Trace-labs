const { execFileSync } = require("child_process");
const path = require("path");
const fs = require("fs");

const plist = path.join(
  __dirname, "..", "node_modules", "electron", "dist",
  "Electron.app", "Contents", "Info.plist"
);

if (process.platform !== "darwin" || !fs.existsSync(plist)) process.exit(0);

const pb = "/usr/libexec/PlistBuddy";
execFileSync(pb, ["-c", "Set CFBundleName Trace Labs", plist]);
execFileSync(pb, ["-c", "Set CFBundleDisplayName Trace Labs", plist]);
console.log("Patched Electron.app bundle name → Trace Labs");
