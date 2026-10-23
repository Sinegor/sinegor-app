const { test } = require("node:test");
const assert = require("node:assert/strict");
const { sanitize } = require("./reporter.cjs");
test("failure diagnostics redact login URLs, cookies and known secrets", () => {
  const output = sanitize(
    "goto http://localhost/auth/magic-link#token=opaque-link-secret\nCookie: sinegor_session=private-session\npassword=unique-private-password\nexpect 503 to equal 200",
    ["unique-private-password"],
  );
  assert.ok(!output.includes("opaque-link-secret"));
  assert.ok(!output.includes("private-session"));
  assert.ok(!output.includes("unique-private-password"));
  assert.ok(output.includes("expect 503 to equal 200"));
});
test("redaction preserves useful assertion context", () => {
  assert.equal(
    sanitize("Expected status 200\nReceived 503", []),
    "Expected status 200\nReceived 503",
  );
});
