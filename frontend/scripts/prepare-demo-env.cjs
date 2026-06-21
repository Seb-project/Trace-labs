const fs = require("fs");
const path = require("path");

const repoRoot = path.resolve(__dirname, "..", "..");
const outputDir = path.join(repoRoot, "dist", "demo");
const outputFile = path.join(outputDir, "backend.env");
const sourceFile = process.env.TRACELABS_BUNDLED_ENV_FILE
  ? path.resolve(process.env.TRACELABS_BUNDLED_ENV_FILE)
  : "";
const apiKey = process.env.TRACELABS_DEMO_OPENAI_API_KEY || "";

function defaultEnv() {
  return [
    "# Trace Labs bundled demo configuration.",
    "# This file is copied into the installed app's user-data folder on first launch.",
    "OPENAI_MODEL=gpt-5.5",
    "DATASHEET_LIVE_SEARCH_ENABLED=true",
    "TRACELABS_LCSC_LOOKUP_ENABLED=true",
    ""
  ].join("\n");
}

fs.mkdirSync(outputDir, { recursive: true });

if (sourceFile) {
  if (!fs.existsSync(sourceFile)) {
    throw new Error(`TRACELABS_BUNDLED_ENV_FILE does not exist: ${sourceFile}`);
  }
  fs.copyFileSync(sourceFile, outputFile);
  console.log(`Prepared bundled backend env from ${sourceFile}`);
} else if (apiKey) {
  fs.writeFileSync(
    outputFile,
    [
      "OPENAI_API_KEY=" + apiKey,
      "OPENAI_MODEL=" + (process.env.OPENAI_MODEL || "gpt-5.5"),
      "DATASHEET_LIVE_SEARCH_ENABLED=true",
      "TRACELABS_LCSC_LOOKUP_ENABLED=true",
      ""
    ].join("\n"),
    "utf8"
  );
  console.log("Prepared bundled backend env from TRACELABS_DEMO_OPENAI_API_KEY");
} else {
  fs.writeFileSync(outputFile, defaultEnv(), "utf8");
  console.log("Prepared bundled backend env without OPENAI_API_KEY");
}
