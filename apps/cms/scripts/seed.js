// Explicit, idempotent import of approved F4 content as drafts. No auto-publishing.
require("dotenv").config();
const { createStrapi } = require("@strapi/strapi");
async function main() {
  const app = await createStrapi().load();
  try {
    for (const { kind, data } of require("./f4-content.json")) {
      const uid = kind === "pages" ? "api::page.page" : "api::service.service";
      const found = await app
        .documents(uid)
        .findMany({ filters: { slug: data.slug }, status: "draft" });
      if (!found.length)
        await app.documents(uid).create({ data, status: "draft" });
    }
  } finally {
    await app.destroy();
  }
}
main().catch((error) => {
  console.error(
    "CMS content import failed:",
    error.name,
    error.code || "configuration",
  );
  process.exitCode = 1;
});
