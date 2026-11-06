// Standalone diagnostic: real HTTP authentication and PostgreSQL fault injection.
// Exit 0 = safe logout observed; 2 = F-02 reproduced; 1 = incomplete/check failed.
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const crypto = require("node:crypto");
const { spawnSync } = require("node:child_process");
const { createRequire } = require("node:module");
const { setTimeout: delay } = require("node:timers/promises");

const options = require("node:util").parseArgs({
  options: { "project-root": { type: "string" }, report: { type: "string" } },
}).values;
const root = path.resolve(
  options["project-root"] || path.join(__dirname, "../../.."),
);
if (!options.report) throw new Error("Use --report with a new JSON file");
const reportPath = path.resolve(options.report);
// Reserve the output without overwriting any previous result.
const reportFd = fs.openSync(reportPath, "wx", 0o600);
const originalCwd = process.cwd();
const runId = crypto.randomBytes(6).toString("hex");
const container = `sinegor-strapi-sessions-${runId}`;
const label = "sinegor.strapi-sessions.run";
const privateDir = fs.mkdtempSync(
  path.join(os.tmpdir(), "sinegor-strapi-sessions-"),
);
fs.chmodSync(privateDir, 0o700);
const result = {
  run_id: runId,
  checks: [],
  scenarios: [],
  completed: false,
  cleanup: false,
};
let app;
let containerAttempted = false;
let stage = "preflight";

function check(condition, name) {
  if (!condition) {
    result.failed_check = name;
    throw new Error(name);
  }
  result.checks.push(name);
}

function docker(...args) {
  const response = spawnSync("docker", args, {
    encoding: "utf8",
    timeout: 30000,
  });
  if (response.status !== 0) throw new Error("Docker operation failed");
  return response.stdout.trim();
}

async function main() {
  // Never inherit live connection variables, dotenv paths, or node preload options.
  const keep = new Set(["PATH", "HOME", "USER", "LANG", "LC_ALL"]);
  for (const name of Object.keys(process.env))
    if (!keep.has(name)) delete process.env[name];
  const password = crypto.randomBytes(32).toString("hex");
  fs.writeFileSync(
    path.join(privateDir, "postgres.env"),
    `POSTGRES_USER=fixture\nPOSTGRES_PASSWORD=${password}\nPOSTGRES_DB=cms_sessions_test\n`,
    { mode: 0o600 },
  );
  docker("image", "inspect", "postgres:16");
  containerAttempted = true;
  docker(
    "run",
    "-d",
    "--name",
    container,
    "--label",
    `${label}=${runId}`,
    "--env-file",
    path.join(privateDir, "postgres.env"),
    "-p",
    "127.0.0.1::5432",
    "--mount",
    "type=tmpfs,destination=/var/lib/postgresql/data,tmpfs-size=536870912",
    "postgres:16",
  );
  let ready = false;
  for (let attempt = 0; attempt < 100; attempt++) {
    const probe = spawnSync(
      "docker",
      ["exec", container, "pg_isready", "-h", "127.0.0.1", "-U", "fixture"],
      { stdio: "ignore", timeout: 5000 },
    );
    if (probe.status === 0) {
      ready = true;
      break;
    }
    await delay(100);
  }
  check(ready, "disposable PostgreSQL ready");
  const port = docker("port", container, "5432/tcp").split(":").at(-1);
  const cmsSource = path.join(root, "apps/cms");
  const workspace = path.join(privateDir, "cms");
  fs.mkdirSync(workspace);
  for (const name of ["config", "src", "package.json"]) {
    fs.cpSync(path.join(cmsSource, name), path.join(workspace, name), {
      recursive: true,
      filter: (source) => !fs.lstatSync(source).isSymbolicLink(),
    });
  }
  fs.mkdirSync(path.join(workspace, "public/uploads"), { recursive: true });
  fs.symlinkSync(
    path.join(cmsSource, "node_modules"),
    path.join(workspace, "node_modules"),
    "dir",
  );
  // Test-only logger configuration: upstream database errors can contain SQL values.
  fs.writeFileSync(
    path.join(workspace, "config/logger.js"),
    'module.exports = { level: "silent" };\n',
  );
  Object.assign(process.env, {
    NODE_ENV: "test",
    HOST: "127.0.0.1",
    PORT: "0",
    CMS_PUBLIC_ORIGIN: "http://localhost",
    DATABASE_HOST: "127.0.0.1",
    DATABASE_PORT: port,
    DATABASE_NAME: "cms_sessions_test",
    DATABASE_USERNAME: "fixture",
    DATABASE_PASSWORD: password,
    DATABASE_SSL: "false",
    STRAPI_TELEMETRY_DISABLED: "true",
    STRAPI_DISABLE_UPDATE_NOTIFICATION: "true",
  });
  for (const name of [
    "APP_KEYS",
    "ADMIN_JWT_SECRET",
    "API_TOKEN_SALT",
    "TRANSFER_TOKEN_SALT",
    "ENCRYPTION_KEY",
    "JWT_SECRET",
  ])
    process.env[name] = crypto.randomBytes(32).toString("hex");
  process.chdir(workspace);
  const cmsRequire = createRequire(path.join(workspace, "package.json"));
  result.strapi_version = cmsRequire("@strapi/strapi/package.json").version;
  stage = "Strapi bootstrap";
  app = await cmsRequire("@strapi/strapi").createStrapi().load();
  // The matrix makes >5 fixture logins in 5 minutes; keep the real middleware,
  // raising only its test-instance quota. Production configuration is untouched.
  app.config.set("admin.rateLimit", { enabled: true, max: 1000 });
  // Mount the actual application without CLI banners or production admin assets.
  await app.server.mount();
  await new Promise((resolve, reject) => {
    app.server.httpServer.once("error", reject);
    app.server.httpServer.listen(0, "127.0.0.1", resolve);
  });
  const origin = `http://127.0.0.1:${app.server.httpServer.address().port}`;
  const credentials = {
    email: "sessions@example.invalid",
    password: `Test-${crypto.randomBytes(24).toString("hex")}!1a`,
  };
  async function request(route, { method = "GET", token, cookie, body } = {}) {
    const response = await fetch(origin + route, {
      method,
      signal: AbortSignal.timeout(10000),
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(cookie ? { Cookie: cookie } : {}),
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    return {
      status: response.status,
      cookies: response.headers.getSetCookie(),
      body: await response.json(),
    };
  }
  const refreshCookie = (response) =>
    response.cookies
      .find((value) => value.startsWith("strapi_admin_refresh="))
      ?.split(";")[0];
  const me = (token) => request("/admin/users/me", { token });
  const renew = (session) =>
    request("/admin/access-token", {
      method: "POST",
      cookie: session.cookie,
      body: {},
    });
  const logout = (session, targeted) =>
    request("/admin/logout", {
      method: "POST",
      token: session.token,
      cookie: session.cookie,
      body: targeted ? { deviceId: session.deviceId } : {},
    });
  function sessionFrom(response, deviceId) {
    const token = response.body.data?.token;
    const cookie = refreshCookie(response);
    if (response.status !== 200)
      result.unexpected_auth_status = response.status;
    check(
      response.status === 200 && !!token && !!cookie,
      "HTTP login issues real access/refresh credentials",
    );
    const payload = JSON.parse(Buffer.from(token.split(".")[1], "base64url"));
    return { token, cookie, deviceId, sessionId: payload.sessionId };
  }
  async function login(rememberMe) {
    const deviceId = crypto.randomUUID();
    return sessionFrom(
      await request("/admin/login", {
        method: "POST",
        body: { ...credentials, deviceId, rememberMe },
      }),
      deviceId,
    );
  }
  const deviceId = crypto.randomUUID();
  stage = "first admin registration";
  const registered = sessionFrom(
    await request("/admin/register-admin", {
      method: "POST",
      body: {
        ...credentials,
        firstname: "Synthetic",
        lastname: "Session test",
        deviceId,
      },
    }),
    deviceId,
  );
  check(
    (await me(registered.token)).status === 200,
    "registered admin can access protected endpoint",
  );
  await logout(registered, false);
  check(
    (await me()).status === 401,
    "protected endpoint rejects unauthenticated requests",
  );

  // Use a real failing DELETE, without replacing installed code or service methods.
  const table = app.db.metadata.get("admin::session").tableName;
  await app.db.connection.raw("CREATE SEQUENCE t12_delete_attempts");
  await app.db.connection
    .raw(`CREATE FUNCTION t12_reject_session_delete() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN PERFORM nextval('t12_delete_attempts'); RAISE EXCEPTION 'synthetic session deletion failure'; END; $$`);
  const faultOn = async () => {
    await app.db.connection.raw("ALTER SEQUENCE t12_delete_attempts RESTART");
    await app.db.connection.raw(
      "CREATE TRIGGER t12_reject_delete BEFORE DELETE ON ?? FOR EACH ROW EXECUTE FUNCTION t12_reject_session_delete()",
      [table],
    );
  };
  const faultOff = () =>
    app.db.connection.raw("DROP TRIGGER t12_reject_delete ON ??", [table]);

  for (const rememberMe of [false, true]) {
    for (const targeted of [true, false]) {
      for (const fault of [false, true]) {
        stage = `logout remember=${rememberMe} targeted=${targeted} fault=${fault}`;
        const session = await login(rememberMe);
        const other = await login(rememberMe);
        check(
          (await me(session.token)).status === 200,
          "old access credential works before logout",
        );
        check(
          (
            await app
              .sessionManager("admin")
              .validateRefreshToken(session.cookie.split("=")[1])
          ).isValid,
          "old refresh credential is valid before logout",
        );
        if (fault) await faultOn();
        let response;
        try {
          response = await logout(session, targeted);
        } finally {
          if (fault) await faultOff();
        }
        const accessStatus = (await me(session.token)).status;
        const rowSurvives = !!(await app.db
          .query("admin::session")
          .findOne({ where: { sessionId: session.sessionId } }));
        const refresh = await renew(session);
        const refreshedAccessStatus = refresh.body.data?.token
          ? (await me(refresh.body.data.token)).status
          : null;
        const otherAccessStatus = (await me(other.token)).status;
        const clear = response.cookies.some(
          (cookie) =>
            cookie.startsWith("strapi_admin_refresh=;") &&
            /expires=Thu, 01 Jan 1970/i.test(cookie),
        );
        check(clear, "logout expires refresh cookie");
        const observation = {
          remember_me: rememberMe,
          scope: targeted ? "device" : "all",
          delete_fault: fault,
          logout_status: response.status,
          refresh_cookie_cleared: clear,
          old_access_status: accessStatus,
          session_row_survives: rowSurvives,
          old_refresh_exchange_status: refresh.status,
          refreshed_access_status: refreshedAccessStatus,
          other_device_access_status: otherAccessStatus,
        };
        result.scenarios.push(observation);
        if (!fault) {
          check(
            response.status === 200 &&
              accessStatus === 401 &&
              !rowSurvives &&
              refresh.status === 401,
            "normal logout rejects both previous credentials",
          );
          check(
            otherAccessStatus === (targeted ? 200 : 401),
            "logout scope respects device selection",
          );
        } else {
          const attempts = await app.db.connection.raw(
            "SELECT is_called FROM t12_delete_attempts",
          );
          check(
            attempts.rows[0].is_called,
            "real PostgreSQL DELETE fault reached",
          );
          observation.unsafe =
            response.status === 200 &&
            accessStatus === 200 &&
            rowSurvives &&
            refresh.status === 200 &&
            refreshedAccessStatus === 200;
          check(
            observation.unsafe ||
              (response.status >= 400 &&
                accessStatus === 401 &&
                refresh.status === 401),
            "fault outcome is classified without assuming successful revocation",
          );
        }
        // A fresh login after fault removal must work, then revoke every fixture session.
        const recovered = await login(rememberMe);
        check(
          (await me(recovered.token)).status === 200,
          "login works after fault removal",
        );
        check(
          (await logout(recovered, false)).status === 200,
          "recovery logout succeeds",
        );
        check(
          (await me(session.token)).status === 401 &&
            (await renew(session)).status === 401,
          "recovery revokes original credentials",
        );
      }
    }
  }
  stage = "CMS model regression";
  const docs = app.documents("api::public-document.public-document");
  const created = await docs.create({
    status: "draft",
    data: {
      title: "Synthetic session regression",
      slug: "synthetic-session-test",
      revisedOn: "2026-11-04",
      body: [
        {
          type: "paragraph",
          children: [{ type: "text", text: "Synthetic content" }],
        },
      ],
    },
  });
  await docs.update({
    documentId: created.documentId,
    data: { title: "Edited synthetic document" },
  });
  await docs.publish({ documentId: created.documentId });
  const published = await request(
    "/api/public-content/documents/synthetic-session-test",
  );
  check(
    published.status === 200 &&
      published.body.data.title === "Edited synthetic document",
    "CMS document create/edit/publish reaches public HTTP endpoint",
  );
  await docs.unpublish({ documentId: created.documentId });
  check(
    (await request("/api/public-content/documents/synthetic-session-test"))
      .status === 404,
    "unpublished CMS document returns 404",
  );
  result.reproduced_f02 = result.scenarios.some((scenario) => scenario.unsafe);
  result.completed = true;
}

async function finish() {
  let cleaned = true;
  try {
    if (app) await app.destroy();
  } catch {
    cleaned = false;
  }
  try {
    if (
      containerAttempted &&
      docker("ps", "-aq", "--filter", `name=^${container}$`)
    ) {
      if (
        docker(
          "inspect",
          "-f",
          `{{ index .Config.Labels "${label}" }}`,
          container,
        ) !== runId
      )
        throw new Error("Container ownership mismatch");
      docker("rm", "-f", container);
    }
  } catch {
    cleaned = false;
  }
  process.chdir(originalCwd);
  try {
    fs.rmSync(privateDir, { recursive: true, force: true });
  } catch {
    cleaned = false;
  }
  result.cleanup = cleaned;
  fs.writeFileSync(reportFd, JSON.stringify(result, null, 2) + "\n");
  fs.closeSync(reportFd);
  console.log(
    JSON.stringify({
      completed: result.completed,
      reproduced_f02: result.reproduced_f02,
      scenarios: result.scenarios.length,
      checks: result.checks.length,
      cleanup: cleaned,
      failed_stage: result.failed_stage,
    }),
  );
  process.exitCode =
    !result.completed || !cleaned ? 1 : result.reproduced_f02 ? 2 : 0;
}
main()
  .catch(() => {
    result.failed_stage = stage;
  })
  .finally(finish);
