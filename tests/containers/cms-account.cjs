// Fixture account on the isolated CMS copy only; never modifies content.
const assert = require("node:assert/strict");
const { createStrapi } = require("@strapi/strapi");

(async () => {
  assert.equal(process.env.LOCAL_CONTAINER_CHECK, "yes");
  assert.ok(process.env.CMS_CHECK_PASSWORD?.length >= 32);
  const app = await createStrapi().load();
  try {
    const role = await app.db.query("admin::role").findOne({
      where: { code: "strapi-super-admin" },
    });
    assert.ok(role);
    const existing = await app.db.query("admin::user").findOne({
      where: { email: "vi0-cms@example.org" },
    });
    // Fixture insertion avoids the invitation service's detached metrics query
    // racing app.destroy(). Password validation still uses the real hash service.
    const data = {
      email: "vi0-cms@example.org",
      password: await app
        .service("admin::auth")
        .hashPassword(process.env.CMS_CHECK_PASSWORD),
      firstname: "Synthetic",
      lastname: "Container check",
      isActive: true,
      roles: [role.id],
    };
    if (existing) {
      await app.db
        .query("admin::user")
        .update({ where: { id: existing.id }, data });
    } else {
      await app.db.query("admin::user").create({ data });
    }
    console.log("PASS: temporary CMS admin created on isolated copy");
  } finally {
    await app.destroy();
  }
})().catch(() => {
  console.error("FAIL: CMS fixture setup");
  process.exitCode = 1;
});
