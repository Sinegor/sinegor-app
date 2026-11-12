const assert = require("node:assert/strict");
const test = require("node:test");
const server = require("../config/server");
const fs = require("node:fs");
const path = require("node:path");
const { Writable } = require("node:stream");
const { createLogger, winston } = require("@strapi/logger");

function config(proxied) {
  const env = (name, fallback) => fallback;
  env.int = (name, fallback) => fallback;
  env.array = () => ["test-key"];
  env.bool = (name, fallback) =>
    name === "CMS_BEHIND_PROXY" ? proxied : fallback;
  return server({ env });
}

test("trusts the single TLS proxy only when explicitly enabled", () => {
  assert.deepEqual(config(true).proxy, { koa: true, maxIpsCount: 1 });
  assert.equal(config(false).proxy.koa, false);
});

test("production logging excludes raw paths, exception text and metadata", () => {
  const file = path.join(__dirname, "../config/env/production/logger.js");
  assert.ok(fs.existsSync(file), "production-safe logging config must exist");
  const lines = [];
  const stream = new Writable({
    write(chunk, encoding, callback) {
      lines.push(chunk.toString());
      callback();
    },
  });
  const logger = createLogger({
    ...require(file),
    transports: [new winston.transports.Stream({ stream })],
  });
  logger.http("GET /admin?token=private-canary");
  logger.error("SQL parameter private-canary", {
    cookie: "private-canary",
    stack: "private-canary",
  });
  assert.equal(lines.length, 1);
  assert.equal(JSON.parse(lines[0]).message, "cms_error");
  assert.ok(!lines.join("").includes("private-canary"));
});
