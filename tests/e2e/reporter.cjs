const fs = require("node:fs");
const path = require("node:path");
function sanitize(text, secrets = []) {
  let safe = String(text).replace(/\u001b\[[0-9;]*m/g, "");
  for (const secret of secrets.filter(
    (value) => typeof value === "string" && value.length >= 8,
  ))
    safe = safe.split(secret).join("[REDACTED]");
  return safe
    .replace(/([#?&]token=)[^\s"'<>]+/gi, "$1[REDACTED]")
    .replace(
      /(?:set-cookie|cookie|authorization|x-csrf-token)\s*:[^\n]*/gi,
      "[REDACTED HEADER]",
    )
    .replace(
      /^.*\[(?:SQL|parameters):.*$/gim,
      "[REDACTED DATABASE DIAGNOSTIC]",
    );
}
class SafeReporter {
  constructor() {
    this.tests = [];
    this.errors = [];
    const config = JSON.parse(fs.readFileSync(process.env.SINEGOR_E2E_CONFIG));
    this.secrets = [
      config.control_key,
      config.admin.password,
      config.admin.totp,
      config.api_env.SESSION_SECRET,
      config.api_env.AUTH_ENCRYPTION_KEY,
      config.api_env.SMTP_PASSWORD,
      config.api_env.DATABASE_URL,
      config.cms_env.DATABASE_PASSWORD,
    ];
  }
  onTestEnd(test, result) {
    this.tests.push({
      title: test.title,
      status: result.status,
      durationMs: result.duration,
      ...(result.errors.length
        ? {
            error: sanitize(
              result.errors.map((e) => e.message).join("\n"),
              this.secrets,
            ),
          }
        : {}),
    });
  }
  onError(error) {
    this.errors.push(sanitize(error.message, this.secrets));
  }
  onEnd(result) {
    fs.writeFileSync(
      path.join(process.env.SINEGOR_E2E_OUTPUT, "results.json"),
      JSON.stringify(
        { status: result.status, tests: this.tests, errors: this.errors },
        null,
        2,
      ) + "\n",
    );
  }
}
module.exports = SafeReporter;
module.exports.sanitize = sanitize;
