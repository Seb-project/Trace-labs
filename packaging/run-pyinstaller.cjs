const { spawnSync } = require("child_process");
const fs = require("fs");
const path = require("path");

const repoRoot = path.resolve(__dirname, "..");
const venvPython = process.platform === "win32"
  ? path.join(repoRoot, ".venv", "Scripts", "python.exe")
  : path.join(repoRoot, ".venv", "bin", "python");
const python = fs.existsSync(venvPython) ? venvPython : (process.env.PYTHON || "python");

const result = spawnSync(
  python,
  ["-m", "PyInstaller", "packaging/tracelabs-backend.spec", "--clean", "--noconfirm"],
  {
    cwd: repoRoot,
    stdio: "inherit",
    shell: false
  }
);

if (result.error) {
  throw result.error;
}

process.exit(result.status ?? 1);
