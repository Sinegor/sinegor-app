const { test } = require("node:test");
const assert = require("node:assert/strict");
const { seedPublicDocuments } = require("../scripts/seed-documents");
const local = {
  NODE_ENV: "development",
  DATABASE_HOST: "127.0.0.1",
  HOST: "127.0.0.1",
  CMS_PUBLIC_ORIGIN: "http://localhost:1337",
};
function fixture() {
  const records = [];
  return {
    records,
    documents(uid) {
      assert.equal(uid, "api::public-document.public-document");
      return {
        async findMany({ filters, status }) {
          return records.filter(
            (d) =>
              d.slug === filters.slug &&
              (status === "published" ? d.publishedAt : !d.publishedAt),
          );
        },
        async create({ data, status }) {
          const doc = {
            ...structuredClone(data),
            documentId: String(records.length + 1),
            publishedAt: status === "published" ? "2026-11-04" : null,
          };
          records.push(doc);
          return doc;
        },
      };
    },
  };
}
test("creates exactly three neutral noindex drafts and is idempotent", async () => {
  const app = fixture();
  assert.deepEqual(await seedPublicDocuments(app), { created: 3, skipped: 0 });
  assert.deepEqual(
    app.records.map((d) => d.slug),
    ["privacy-policy", "personal-data-consent", "service-rules"],
  );
  for (const d of app.records) {
    assert.equal(d.publishedAt, null);
    assert.equal(d.body[0].children[0].text, "Документ готовится к публикации");
    assert.equal(d.seo.noindex, true);
    assert.match(d.revisedOn, /^\d{4}-\d{2}-\d{2}$/);
  }
  const original = structuredClone(app.records);
  assert.deepEqual(await seedPublicDocuments(app), { created: 0, skipped: 3 });
  assert.deepEqual(app.records, original);
});
test("does not overwrite editorial content, republish drafts or duplicate published-only records", async () => {
  const app = fixture();
  await seedPublicDocuments(app);
  app.records[0].title = "Owner revision";
  app.records[0].body[0].children[0].text = "Owner text";
  app.records[0].seo.noindex = false;
  app.records[1].publishedAt = "2026-11-03";
  const original = structuredClone(app.records);
  assert.deepEqual(
    await seedPublicDocuments(app, { publishLocal: true, environment: local }),
    { created: 0, skipped: 3 },
  );
  assert.deepEqual(app.records, original);
});
test("explicit local publication creates only neutral noindex records", async () => {
  const app = fixture();
  await seedPublicDocuments(app, { publishLocal: true, environment: local });
  assert.equal(app.records.length, 3);
  assert.ok(app.records.every((d) => d.publishedAt && d.seo.noindex));
});
test("refuses placeholder publication outside explicit local development before writing", async () => {
  for (const environment of [
    {},
    { ...local, NODE_ENV: "production" },
    { ...local, NODE_ENV: "test" },
    { ...local, DATABASE_HOST: "db.remote" },
    { ...local, HOST: "0.0.0.0" },
    { ...local, CMS_PUBLIC_ORIGIN: "https://public.example" },
  ]) {
    const app = fixture();
    await assert.rejects(
      seedPublicDocuments(app, { publishLocal: true, environment }),
    );
    assert.equal(app.records.length, 0);
  }
});
