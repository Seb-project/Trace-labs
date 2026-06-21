const { app, BrowserWindow, dialog, shell } = require("electron");
const { spawn } = require("child_process");
const fs = require("fs");
const http = require("http");
const path = require("path");

app.setName("Trace Labs");

const BACKEND_HOST = "127.0.0.1";
const BACKEND_PORT = "8765";
const BACKEND_BASE_URL = `http://${BACKEND_HOST}:${BACKEND_PORT}`;

let backendProcess = null;

function isProductionRuntime() {
  return app.isPackaged || process.env.NODE_ENV === "production";
}

function backendExecutablePath() {
  if (process.env.TRACELABS_BACKEND_EXECUTABLE) {
    return process.env.TRACELABS_BACKEND_EXECUTABLE;
  }
  const executable = process.platform === "win32" ? "tracelabs-backend.exe" : "tracelabs-backend";
  return path.join(process.resourcesPath, "backend", executable);
}

function ensureBackendEnvFile(userDataDir) {
  const envFile = path.join(userDataDir, "backend.env");
  if (!fs.existsSync(envFile)) {
    const bundledEnvFile = path.join(process.resourcesPath, "demo", "backend.env");
    if (fs.existsSync(bundledEnvFile)) {
      fs.copyFileSync(bundledEnvFile, envFile);
    } else {
      fs.writeFileSync(
        envFile,
        [
          "# Trace Labs backend configuration.",
          "# Add OPENAI_API_KEY here if you want live AI/datasheet features on this machine.",
          "# OPENAI_API_KEY=sk-your-key-here",
          "OPENAI_MODEL=gpt-5.5",
          "DATASHEET_LIVE_SEARCH_ENABLED=true",
          "TRACELABS_LCSC_LOOKUP_ENABLED=true",
          ""
        ].join("\n"),
        "utf8"
      );
    }
  }
  return envFile;
}

function requestBackendHealth() {
  return new Promise((resolve) => {
    const request = http.get(`${BACKEND_BASE_URL}/health`, (response) => {
      response.resume();
      resolve(response.statusCode >= 200 && response.statusCode < 500);
    });
    request.setTimeout(1000, () => {
      request.destroy();
      resolve(false);
    });
    request.on("error", () => resolve(false));
  });
}

async function waitForBackend(timeoutMs = 20000) {
  const startedAt = Date.now();
  while (Date.now() - startedAt < timeoutMs) {
    if (await requestBackendHealth()) {
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 350));
  }
  throw new Error(`Trace Labs backend did not become ready at ${BACKEND_BASE_URL}`);
}

async function startBackendIfNeeded() {
  if (!isProductionRuntime()) {
    return;
  }
  if (await requestBackendHealth()) {
    return;
  }

  const executable = backendExecutablePath();
  if (!fs.existsSync(executable)) {
    throw new Error(`Bundled backend executable was not found: ${executable}`);
  }

  const userDataDir = app.getPath("userData");
  const dataDir = path.join(userDataDir, "data");
  const generatedBlocksDir = path.join(userDataDir, "generated_blocks");
  const recipesDir = path.join(userDataDir, "recipes");
  const logsDir = path.join(userDataDir, "logs");
  fs.mkdirSync(dataDir, { recursive: true });
  fs.mkdirSync(generatedBlocksDir, { recursive: true });
  fs.mkdirSync(recipesDir, { recursive: true });
  fs.mkdirSync(logsDir, { recursive: true });

  const stdoutLog = fs.createWriteStream(path.join(logsDir, "backend.stdout.log"), { flags: "a" });
  const stderrLog = fs.createWriteStream(path.join(logsDir, "backend.stderr.log"), { flags: "a" });
  const envFile = ensureBackendEnvFile(userDataDir);

  backendProcess = spawn(executable, [], {
    env: {
      ...process.env,
      PYTHONUNBUFFERED: "1",
      TRACELABS_BACKEND_HOST: BACKEND_HOST,
      TRACELABS_BACKEND_PORT: BACKEND_PORT,
      TRACELABS_DATA_DIR: dataDir,
      TRACELABS_GENERATED_BLOCKS_DIR: generatedBlocksDir,
      TRACELABS_RECIPES_DIR: recipesDir,
      TRACELABS_ENV_FILE: envFile
    },
    stdio: ["ignore", "pipe", "pipe"]
  });

  backendProcess.stdout.on("data", (chunk) => stdoutLog.write(chunk));
  backendProcess.stderr.on("data", (chunk) => stderrLog.write(chunk));
  backendProcess.on("exit", () => {
    stdoutLog.end();
    stderrLog.end();
    backendProcess = null;
  });

  await waitForBackend();
}

function stopBackend() {
  if (!backendProcess) {
    return;
  }
  const child = backendProcess;
  backendProcess = null;
  child.kill();
}

function createWindow() {
  const iconPath = path.join(__dirname, "..", "build", "icon.png");
  const win = new BrowserWindow({
    width: 1320,
    height: 900,
    minWidth: 300,
    minHeight: 560,
    title: "Trace Labs",
    icon: fs.existsSync(iconPath) ? iconPath : undefined,
    backgroundColor: "#070b14",
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false
    }
  });

  if (process.platform === "darwin" && !app.isPackaged && fs.existsSync(iconPath)) {
    app.dock.setIcon(iconPath);
  }
  win.setMinimumSize(300, 560);

  const devUrl = process.env.TRACELABS_DEV_URL || "http://127.0.0.1:5173";
  if (isProductionRuntime()) {
    win.loadFile(path.join(__dirname, "..", "dist", "index.html"));
  } else {
    win.loadURL(devUrl);
  }

  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//i.test(url)) {
      shell.openExternal(url);
      return { action: "deny" };
    }
    return { action: "deny" };
  });

  win.webContents.on("will-navigate", (event, url) => {
    if (/^https?:\/\//i.test(url) && !url.startsWith(devUrl)) {
      event.preventDefault();
      shell.openExternal(url);
    }
  });
}

app.whenReady().then(async () => {
  try {
    await startBackendIfNeeded();
    createWindow();
  } catch (error) {
    dialog.showErrorBox("Trace Labs could not start", error instanceof Error ? error.message : String(error));
    app.quit();
  }
});

app.on("before-quit", stopBackend);

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});
