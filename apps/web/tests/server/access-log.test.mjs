import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { readdir, stat } from "node:fs/promises";
import { createServer, request } from "node:http";
import { after, before, test } from "node:test";
import { setTimeout as delay } from "node:timers/promises";

let child;
let port;
let stdout = "";
let stderr = "";
const markers = [
  "synthetic-contact+logging@example.invalid",
  "+7 (000) 123-45-67",
  "Тестовый ЖурналИмени",
  "synthetic-special<&>\"'\\\r\nFORGED",
  "synthetic-auth-credential",
  "synthetic-session-value",
  "synthetic-invalid-host",
];

async function send(path, { method = "GET", body, headers = {} } = {}) {
  return new Promise((resolve, reject) => {
    const req = request(
      {
        host: "127.0.0.1",
        port,
        path,
        method,
        headers: {
          Cookie: `session=${markers[5]}`,
          Authorization: `Bearer ${markers[4]}`,
          Referer: `https://example.invalid/?q=${encodeURIComponent(markers[0])}`,
          ...(body ? { "Content-Type": "application/json" } : {}),
          ...headers,
        },
      },
      (res) => {
        let text = "";
        res.setEncoding("utf8");
        res.on("data", (chunk) => {
          text += chunk;
        });
        res.on("end", () =>
          resolve({ status: res.statusCode, headers: res.headers, text }),
        );
      },
    );
    req.on("error", reject);
    req.end(body);
  });
}

function assertPrivate(output) {
  for (const marker of markers) {
    for (const representation of [
      marker,
      encodeURIComponent(marker),
      encodeURI(marker),
      JSON.stringify(marker).slice(1, -1),
    ]) {
      assert.ok(
        !output.includes(representation),
        "Synthetic sensitive value leaked to process output",
      );
    }
  }
}

function records(output) {
  return output.split("\n").flatMap((line) => {
    try {
      const value = JSON.parse(line);
      return value.event === "http_access" ? [value] : [];
    } catch {
      return [];
    }
  });
}

before(
  async () => {
    const reservation = createServer();
    reservation.listen(0, "127.0.0.1");
    await once(reservation, "listening");
    port = reservation.address().port;
    await new Promise((resolve) => reservation.close(resolve));
    child = spawn("npm", ["start"], {
      cwd: new URL("../../", import.meta.url),
      env: {
        PATH: process.env.PATH,
        HOST: "127.0.0.1",
        PORT: String(port),
      },
      stdio: ["ignore", "pipe", "pipe"],
      detached: true,
    });
    child.stdout.setEncoding("utf8").on("data", (chunk) => {
      stdout += chunk;
    });
    child.stderr.setEncoding("utf8").on("data", (chunk) => {
      stderr += chunk;
    });
    for (let i = 0; i < 200; i++) {
      if (child.exitCode !== null)
        throw new Error("SSR process exited before listening");
      try {
        if ((await send("/auth/admin")).status === 200) {
          await delay(25);
          return;
        }
      } catch {}
      await delay(50);
    }
    throw new Error("SSR process did not listen");
  },
  { timeout: 20_000 },
);

after(async () => {
  if (child && child.exitCode === null) {
    const exited = once(child, "exit");
    process.kill(-child.pid, "SIGTERM");
    await exited;
  }
});

test("search queries never reach stdout/stderr while customer search shell still renders", async () => {
  const start = stdout.length,
    errorStart = stderr.length;
  for (const marker of markers.slice(0, 4)) {
    const result = await send(
      `/admin/customers?q=${encodeURIComponent(marker)}&offset=0`,
    );
    assert.equal(result.status, 200);
    assert.match(result.text, /<html/);
    assert.equal(result.headers["cache-control"], "no-store");
  }
  await delay(25);
  assertPrivate(stdout.slice(start) + stderr.slice(errorStart));
  const logs = records(stdout.slice(start));
  assert.equal(
    logs.length,
    4,
    "Each request must retain a diagnostic access record",
  );
  for (const log of logs) {
    assert.equal(log.method, "GET");
    assert.equal(log.path, "/admin/customers");
    assert.equal(log.status, 200);
    assert.ok(Number.isFinite(log.duration_ms) && log.duration_ms >= 0);
  }
});

test("dynamic segments, Single Fetch and unknown/error routes use safe templates", async () => {
  const start = stdout.length,
    errorStart = stderr.length;
  const requests = [
    ["/_.data", "/", 200],
    ["/admin/customers/_.data", "/admin/customers", 200],
    [
      "/admin/customers/" + encodeURIComponent(markers[0]),
      "/admin/customers/:customerId",
      200,
    ],
    [
      "/admin/orders/" + encodeURIComponent(markers[1]),
      "/admin/orders/:orderId",
      200,
    ],
    [
      "/customer/orders/" + encodeURIComponent(markers[2]),
      "/customer/orders/:orderId",
      200,
    ],
    ["/documents/" + encodeURIComponent(markers[3]), "/documents/:slug", 404],
    [
      "/publications/" + encodeURIComponent(markers[0]),
      "/publications/:slug",
      404,
    ],
    ["/pages/" + encodeURIComponent(markers[2]), "/pages/:slug", 404],
    ["/services/" + encodeURIComponent(markers[0]), "/services/:slug", 404],
    [
      "/admin/customers/" + encodeURIComponent(markers[0]) + ".data",
      "/admin/customers/:customerId",
      200,
    ],
    ["/unknown/" + encodeURIComponent(markers[0]), "/:unmatched", 404],
    ["/assets/" + encodeURIComponent(markers[0]) + ".js", "/assets/*", 404],
    [
      "/admin/customers/" + encodeURIComponent(markers[0]) + "/%ZZ",
      "/:unmatched",
      400,
    ],
  ];
  for (const [path, , status] of requests) {
    const result = await send(path + `?q=${encodeURIComponent(markers[2])}`);
    assert.equal(result.status, status, "Expected SSR/error HTTP status");
    if (path.startsWith("/unknown/"))
      assert.match(result.text, /Страница не найдена/);
  }
  await delay(25);
  assertPrivate(stdout.slice(start) + stderr.slice(errorStart));
  const logs = records(stdout.slice(start));
  assert.equal(logs.length, requests.length);
  for (let i = 0; i < requests.length; i++) {
    assert.equal(logs[i].path, requests[i][1]);
    assert.equal(logs[i].status, requests[i][2]);
    assert.ok(Number.isFinite(logs[i].duration_ms));
  }
});

test("routing errors preserve diagnostics without echoing path, body or credentials", async () => {
  const start = stdout.length,
    errorStart = stderr.length;
  const result = await send(
    `/admin/customers/${encodeURIComponent(markers[0])}?q=${encodeURIComponent(markers[1])}`,
    {
      method: "POST",
      body: JSON.stringify({ name: markers[2], comment: markers[3] }),
    },
  );
  assert.equal(result.status, 405);
  await delay(25);
  assertPrivate(stdout.slice(start) + stderr.slice(errorStart));
  const [log] = records(stdout.slice(start));
  assert.ok(log, "An error must retain an access record");
  assert.equal(log.method, "POST");
  assert.equal(log.path, "/admin/customers/:customerId");
  assert.equal(log.status, 405);
  const errors = stderr
    .slice(errorStart)
    .trim()
    .split("\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line));
  assert.ok(
    errors.some((event) => event.event === "ssr_error" && event.status === 405),
  );
});

test("valid-version discovery rejects malformed nested paths without logging query values", async () => {
  const { assets } = await import("../../build/server/index.js");
  const start = stdout.length,
    errorStart = stderr.length;
  const nested = `/admin/customers/${markers[0]}/%ZZ`;
  const query = new URLSearchParams({ version: assets.version, paths: nested });
  const result = await send(`/__manifest?${query}`);
  const normalizedResult = await send(`/synthetic/../__manifest?${query}`);
  await delay(25);
  assertPrivate(stdout.slice(start) + stderr.slice(errorStart));
  assert.equal(result.status, 400);
  assert.equal(normalizedResult.status, 400);
  const [log] = records(stdout.slice(start));
  assert.equal(log.path, "/__manifest");
  assert.equal(log.status, 400);
  const validQuery = new URLSearchParams({
    version: assets.version,
    paths: `/admin/customers/${encodeURIComponent(markers[0])},/contacts`,
  });
  const valid = await send(`/__manifest?${validQuery}`);
  assert.equal(valid.status, 200);
  assert.ok(JSON.parse(valid.text)["routes/admin/customer"]);
  assert.ok(JSON.parse(valid.text)["routes/public/contacts"]);
  await delay(25);
  assertPrivate(stdout.slice(start) + stderr.slice(errorStart));
});

test("adapter failures retain a safe 500 record without Express exception text", async () => {
  const start = stdout.length,
    errorStart = stderr.length;
  const result = await send(`/auth/admin?q=${encodeURIComponent(markers[0])}`, {
    headers: { Host: `[${markers[6]}` },
  });
  assert.equal(result.status, 500);
  assert.equal(result.text, "Internal Server Error");
  await delay(25);
  assertPrivate(stdout.slice(start) + stderr.slice(errorStart));
  const [log] = records(stdout.slice(start));
  assert.equal(log.path, "/auth/admin");
  assert.equal(log.status, 500);
  assert.ok(Number.isFinite(log.duration_ms));
  const error = JSON.parse(stderr.slice(errorStart).trim());
  assert.equal(error.event, "ssr_adapter_error");
  assert.equal(error.status, 500);
});

test("SSR assets, HEAD, gzip, resource routes and discovery remain available", async () => {
  const html = await send("/auth/admin", { method: "HEAD" });
  assert.equal(html.status, 200);
  assert.equal(html.text, "");
  const compressed = await send("/auth/admin", {
    headers: { "Accept-Encoding": "gzip" },
  });
  assert.equal(compressed.status, 200);
  assert.equal(compressed.headers["content-encoding"], "gzip");
  const page = await send("/auth/admin");
  const asset = page.text.match(/(?:src|href)="(\/assets\/[^\"]+\.js)"/)[1];
  const staticResponse = await send(
    asset + `?q=${encodeURIComponent(markers[0])}`,
  );
  assert.equal(staticResponse.status, 200);
  assert.match(staticResponse.headers["cache-control"], /immutable/);
  assert.equal((await send("/robots.txt")).status, 200);
  assert.equal((await send("/sitemap.xml")).status, 200);
  assert.equal(
    (await send("/__manifest?version=invalid&paths=%2Fadmin%2Fcustomers"))
      .status,
    204,
  );
  await delay(25);
  assertPrivate(stdout + stderr);
});

test("an interrupted static response still emits exactly one private diagnostic record", async () => {
  const directory = new URL("../../build/client/assets/", import.meta.url);
  const assets = await Promise.all(
    (await readdir(directory))
      .filter((file) => /\.(png|jpg|js)$/.test(file))
      .map(async (file) => ({
        file,
        size: (await stat(new URL(file, directory))).size,
      })),
  );
  const asset = assets.sort((a, b) => b.size - a.size)[0];
  assert.ok(
    asset?.size > 256 * 1024,
    "A large static asset exercises interruption",
  );
  const start = stdout.length,
    errorStart = stderr.length;
  await new Promise((resolve, reject) => {
    const req = request(
      {
        host: "127.0.0.1",
        port,
        path: `/assets/${encodeURIComponent(asset.file)}?q=${encodeURIComponent(markers[0])}`,
      },
      (res) => {
        res.once("data", () => res.destroy());
        res.once("close", resolve);
      },
    );
    req.once("error", reject);
    req.end();
  });
  await delay(100);
  assertPrivate(stdout.slice(start) + stderr.slice(errorStart));
  const logs = records(stdout.slice(start));
  assert.equal(logs.length, 1);
  assert.equal(logs[0].path, "/assets/*");
  assert.equal(logs[0].method, "GET");
  assert.equal(logs[0].status, 200);
  assert.equal(logs[0].aborted, true);
  assert.ok(Number.isFinite(logs[0].duration_ms));
});
