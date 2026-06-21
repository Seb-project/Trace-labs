const expected = process.argv[2];

if (!expected) {
  throw new Error("Expected platform argument is required.");
}

if (process.platform !== expected) {
  const labels = {
    darwin: "macOS",
    win32: "Windows",
    linux: "Linux"
  };
  const wanted = labels[expected] || expected;
  const current = labels[process.platform] || process.platform;
  console.error(`This package target must be built on ${wanted}. Current platform: ${current}.`);
  process.exit(1);
}
