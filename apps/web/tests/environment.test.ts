import { execFile } from "node:child_process";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { promisify } from "node:util";
import { expect, it } from "vitest";

const run = promisify(execFile);
const webRoot = fileURLToPath(new URL("../", import.meta.url));
const viteEntry = pathToFileURL(
  join(webRoot, "node_modules/vite/dist/node/index.js"),
).href;

async function proxyTarget(apiOverride?: string) {
  const directory = await mkdtemp(join(tmpdir(), "sinegor-web-env-"));
  try {
    await writeFile(
      join(directory, ".env.development"),
      "API_ORIGIN=http://127.0.0.1:8917\n",
    );
    const env = { ...process.env };
    delete env.API_ORIGIN;
    delete env.CMS_ORIGIN;
    delete env.CMS_MEDIA_ORIGIN;
    if (apiOverride !== undefined) env.API_ORIGIN = apiOverride;
    const { stdout } = await run(
      process.execPath,
      [
        "--input-type=module",
        "-e",
        `const { loadConfigFromFile } = await import(${JSON.stringify(viteEntry)});
         const loaded = await loadConfigFromFile(
           { command: "serve", mode: "development" },
           ${JSON.stringify(join(webRoot, "vite.config.ts"))},
           process.cwd(), "silent"
         );
         process.stdout.write(loaded.config.server.proxy["/api"].target);`,
      ],
      { cwd: directory, env },
    );
    return stdout;
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
}

it("uses API_ORIGIN from .env.development when configuring the API proxy", async () => {
  expect(await proxyTarget()).toBe("http://127.0.0.1:8917");
});

it("preserves an explicit process API_ORIGIN over the development file", async () => {
  expect(await proxyTarget("http://127.0.0.1:8918")).toBe(
    "http://127.0.0.1:8918",
  );
});
