// Explicit, idempotent import. Never runs during CMS startup.
const uid = "api::public-document.public-document";
const documents = [
  { slug: "privacy-policy", title: "Политика обработки персональных данных" },
  {
    slug: "personal-data-consent",
    title: "Согласие на обработку персональных данных",
  },
  { slug: "service-rules", title: "Правила предоставления услуг" },
];

function assertLocalDevelopment(environment) {
  const loopback = new Set(["localhost", "127.0.0.1", "::1", "[::1]"]);
  let origin;
  try {
    origin = new URL(environment.CMS_PUBLIC_ORIGIN);
  } catch {}
  if (
    environment.NODE_ENV !== "development" ||
    !loopback.has(environment.DATABASE_HOST) ||
    !loopback.has(environment.HOST) ||
    !origin ||
    !["http:", "https:"].includes(origin.protocol) ||
    !loopback.has(origin.hostname)
  )
    throw new Error(
      "Temporary documents may only be published in explicit local development",
    );
}

async function seedPublicDocuments(
  app,
  { publishLocal = false, environment = process.env } = {},
) {
  if (publishLocal) assertLocalDevelopment(environment);
  const service = app.documents(uid);
  const result = { created: 0, skipped: 0 };
  for (const document of documents) {
    const query = {
      filters: { slug: document.slug },
      fields: ["documentId"],
      limit: 1,
    };
    const draft = await service.findMany({ ...query, status: "draft" });
    const published = await service.findMany({ ...query, status: "published" });
    if (draft.length || published.length) {
      result.skipped++;
      continue;
    }
    await service.create({
      status: publishLocal ? "published" : "draft",
      data: {
        ...document,
        body: [
          {
            type: "paragraph",
            children: [
              { type: "text", text: "Документ готовится к публикации" },
            ],
          },
        ],
        revisedOn: new Date().toISOString().slice(0, 10),
        seo: { noindex: true },
      },
    });
    result.created++;
  }
  return result;
}

async function main() {
  require("dotenv").config();
  const args = process.argv.slice(2);
  if (args.some((arg) => arg !== "--publish-local"))
    throw new Error("Unknown seed option");
  const publishLocal = args.includes("--publish-local");
  if (publishLocal) assertLocalDevelopment(process.env);
  const { createStrapi } = require("@strapi/strapi");
  const app = await createStrapi().load();
  try {
    const result = await seedPublicDocuments(app, { publishLocal });
    console.log(
      `Public documents import: created=${result.created}, skipped=${result.skipped}`,
    );
  } finally {
    await app.destroy();
  }
}
if (require.main === module)
  main().catch(() => {
    console.error(
      "Public documents import failed; check CMS configuration and local publication settings",
    );
    process.exitCode = 1;
  });
module.exports = { seedPublicDocuments };
