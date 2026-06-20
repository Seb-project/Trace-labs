const childProcess = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

const electronRoot = path.join(__dirname, "..", "node_modules", "electron");
const electronPackagePath = path.join(electronRoot, "package.json");

if (!fs.existsSync(electronPackagePath)) {
  console.error("Electron is not installed. Run npm install first.");
  process.exit(1);
}

const electronPackage = require(electronPackagePath);
const platform = process.env.npm_config_platform || process.platform;
const arch = process.env.npm_config_arch || process.arch;
const platformPath = getPlatformPath(platform);
const electronBinary = path.join(electronRoot, "dist", platformPath);
const pathFile = path.join(electronRoot, "path.txt");

if (fs.existsSync(electronBinary) && fs.existsSync(pathFile)) {
  console.log(`Electron binary is installed: ${electronBinary}`);
  process.exit(0);
}

repair().catch((error) => {
  console.error(error);
  process.exit(1);
});

async function repair() {
  const getPackagePath = require.resolve("@electron/get", { paths: [electronRoot] });
  const { downloadArtifact } = require(getPackagePath);
  const checksumsPath = path.join(electronRoot, "checksums.json");
  const checksums = fs.existsSync(checksumsPath) ? require(checksumsPath) : undefined;

  console.log(`Repairing Electron ${electronPackage.version} for ${platform}/${arch}...`);
  const zipPath = await downloadArtifact({
    version: electronPackage.version,
    artifactName: "electron",
    platform,
    arch,
    force: true,
    checksums
  });

  const distPath = path.join(electronRoot, "dist");
  fs.rmSync(distPath, { recursive: true, force: true });
  fs.mkdirSync(distPath, { recursive: true });

  if (platform === "win32") {
    childProcess.execFileSync("powershell", [
      "-NoProfile",
      "-Command",
      `Expand-Archive -Force ${JSON.stringify(zipPath)} ${JSON.stringify(distPath)}`
    ]);
  } else {
    childProcess.execFileSync("unzip", ["-oq", zipPath, "-d", distPath]);
  }

  fs.writeFileSync(pathFile, platformPath);

  if (!fs.existsSync(electronBinary)) {
    throw new Error(`Electron repair did not produce expected binary: ${electronBinary}`);
  }

  fs.chmodSync(electronBinary, fs.statSync(electronBinary).mode | 0o111);
  console.log(`Electron binary repaired: ${electronBinary}`);
}

function getPlatformPath(targetPlatform) {
  switch (targetPlatform) {
    case "mas":
    case "darwin":
      return "Electron.app/Contents/MacOS/Electron";
    case "freebsd":
    case "openbsd":
    case "linux":
      return "electron";
    case "win32":
      return "electron.exe";
    default:
      throw new Error(`Electron builds are not available on ${targetPlatform}/${os.arch()}`);
  }
}
