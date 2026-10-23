const fs = require("node:fs");
const path = require("node:path");
const cp = require("node:child_process");
const crypto = require("node:crypto");
const {
  test,
  expect,
} = require("../../apps/web/node_modules/@playwright/test");
const config = JSON.parse(fs.readFileSync(process.env.SINEGOR_E2E_CONFIG));
function data(action, payload = {}) {
  const reply = cp.spawnSync(
    config.python,
    [path.join(__dirname, "data.py"), action],
    {
      env: {
        ...config.api_env,
        SINEGOR_E2E_CONFIG: process.env.SINEGOR_E2E_CONFIG,
      },
      input: JSON.stringify(payload),
      encoding: "utf8",
      timeout: 35000,
    },
  );
  if (reply.status !== 0)
    throw new Error("E2E data operation failed: " + action);
  return JSON.parse(reply.stdout);
}
async function control(route, payload) {
  const response = await fetch(
    `http://127.0.0.1:${config.ports.control}${route}`,
    {
      headers: { "X-E2E-Key": config.control_key },
      ...(payload ? { method: "POST", body: JSON.stringify(payload) } : {}),
    },
  );
  if (!response.ok) throw new Error("External fixture control failed");
  return response.json();
}
async function cms(payload) {
  const response = await fetch(`http://127.0.0.1:${config.ports.cms_control}`, {
    method: "POST",
    headers: { "X-E2E-Key": config.control_key },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error("CMS fixture management failed");
  return response.json();
}
async function mutate(request, route, payload, method = "POST") {
  const csrf = await request.get(config.origin + "/api/auth/csrf");
  expect(csrf.status()).toBe(200);
  return request.fetch(config.origin + route, {
    method,
    data: payload,
    headers: {
      Origin: config.origin,
      "X-CSRF-Token": (await csrf.json()).csrf_token,
    },
  });
}
async function read(request, route) {
  const response = await request.get(config.origin + route);
  expect(response.status()).toBe(200);
  return response.json();
}
async function download(page, label) {
  const pending = page.waitForEvent("download");
  await page.getByRole("button", { name: label, exact: true }).click();
  const file = await (await pending).path();
  return crypto
    .createHash("sha256")
    .update(fs.readFileSync(file))
    .digest("hex");
}
function runtimeErrors(page) {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  return errors;
}
module.exports = {
  test,
  expect,
  config,
  data,
  control,
  cms,
  mutate,
  read,
  download,
  runtimeErrors,
};
