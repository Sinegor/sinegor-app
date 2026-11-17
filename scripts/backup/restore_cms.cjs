// Loaded only inside the exact offline, disposable CMS image; never exports file metadata.
"use strict";
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const assert = require("node:assert/strict");
const { createRequire } = require("node:module");
const cmsRequire = createRequire(path.join(process.cwd(), "package.json"));
const { createStrapi } = cmsRequire("@strapi/strapi");

function mediaPath(raw) {
  assert.equal(typeof raw, "string");
  assert(raw.startsWith("/uploads/"));
  assert(!/[?#\\\u0000]/.test(raw));
  const decoded = decodeURIComponent(raw);
  const parts = decoded.slice("/uploads/".length).split("/");
  assert(parts.every((part) => part && part !== "." && part !== ".."));
  let filename = path.join(process.cwd(), "public", "uploads");
  for (const part of parts) {
    filename = path.join(filename, part);
    assert(!fs.lstatSync(filename).isSymbolicLink());
  }
  assert(fs.statSync(filename).isFile());
  return filename;
}

async function main() {
  // Load may update the disposable restored schema/store; it cannot reach production.
  const app = await createStrapi().load();
  try {
    const files = await app.db.query("plugin::upload.file").findMany({
      select: ["url", "formats", "provider"],
    });
    const urls = new Set();
    for (const file of files) {
      assert.equal(file.provider, "local");
      urls.add(file.url);
      for (const format of Object.values(file.formats || {})) urls.add(format.url);
    }
    await app.start();
    for (const url of urls) {
      const filename = mediaPath(url);
      const expected = crypto.createHash("sha256").update(fs.readFileSync(filename)).digest("hex");
      const response = await fetch("http://127.0.0.1:1337" + url, {
        redirect: "error", signal: AbortSignal.timeout(15000),
      });
      assert.equal(response.status, 200);
      const received = Buffer.from(await response.arrayBuffer());
      assert.equal(crypto.createHash("sha256").update(received).digest("hex"), expected);
      assert.equal(received.length, fs.statSync(filename).size);
    }
  } finally {
    await app.destroy();
  }
}

main().catch(() => {
  // No Strapi errors, SQL rows, URLs, file names, or credentials leave the fixture.
  process.exitCode = 1;
});
