// Retain the documented entrypoint; the single maintained scenario owns its isolated stack.
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const root = path.resolve(__dirname, "../../..");
const result = spawnSync(
  path.join(root, "apps/api/.venv/bin/python"),
  [path.join(root, "tests/e2e/run.py"), "--suite", "cms"],
  { cwd: root, stdio: "inherit" },
);
if (result.error)
  console.error(
    "Install the backend environment before running the CMS integration test.",
  );
process.exitCode = result.status ?? 1;
