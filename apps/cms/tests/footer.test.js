const { test } = require("node:test");
const assert = require("node:assert/strict");
const controller = require("../src/api/public-content/controllers/public-content");
const app = require("../src/index");
const footerUid = "api::footer-settings.footer-settings";
const documentUid = "api::public-document.public-document";
const published = "2026-11-06T10:00:00.000Z";

async function readFooter(settings, documents = []) {
  const queries = [];
  global.strapi = {
    documents(uid) {
      return {
        async findFirst(query) {
          queries.push({ uid, query });
          return query.status === "published" && settings?.publishedAt
            ? settings
            : null;
        },
        async findMany(query) {
          queries.push({ uid, query });
          return documents;
        },
      };
    },
  };
  const headers = {};
  const ctx = {
    params: { kind: "footer" },
    query: { status: "draft", populate: "*", limit: 1 },
    set(name, value) {
      headers[name] = value;
    },
    notFound() {
      this.status = 404;
    },
  };
  try {
    await controller.list(ctx);
    return { ctx, queries, headers };
  } finally {
    delete global.strapi;
  }
}

test("footer returns empty lists for absent or unpublished configuration", async () => {
  for (const settings of [
    null,
    { usefulLinks: [{ label: "Draft", href: "/draft" }] },
  ]) {
    const { ctx, queries, headers } = await readFooter(settings);
    assert.deepEqual(ctx.body, { data: { documents: [], usefulLinks: [] } });
    assert.equal(queries[0].uid, footerUid);
    assert.equal(queries[0].query.status, "published");
    assert.equal(headers["Cache-Control"], "no-store");
  }
});

test("footer resolves current published documents in configured order and exposes only link fields", async () => {
  const { ctx, queries } = await readFooter(
    {
      publishedAt: published,
      documentId: "private-footer-id",
      documents: [
        { documentId: "c" },
        { documentId: "draft" },
        { documentId: "a" },
        { documentId: "deleted" },
      ],
      usefulLinks: [
        { id: 1, label: "<b>About</b>", href: "/about", secret: "private" },
      ],
    },
    [
      {
        documentId: "a",
        title: "Current A",
        slug: "new-a",
        publishedAt: published,
        body: ["private"],
      },
      { documentId: "draft", title: "Draft", slug: "draft", publishedAt: null },
      {
        documentId: "c",
        title: "Current C",
        slug: "new-c",
        publishedAt: published,
        createdBy: "private",
      },
    ],
  );
  assert.deepEqual(ctx.body, {
    data: {
      documents: [
        { label: "Current C", href: "/documents/new-c" },
        { label: "Current A", href: "/documents/new-a" },
      ],
      usefulLinks: [{ label: "<b>About</b>", href: "/about" }],
    },
  });
  assert.equal(queries[1].uid, documentUid);
  assert.equal(queries[1].query.status, "published");
  assert.equal(queries[1].query.limit, -1);
  assert.deepEqual(queries[1].query.filters.documentId.$in, [
    "c",
    "draft",
    "a",
    "deleted",
  ]);
});

test("footer has no implicit 25-item limit and follows removed/reordered links", async () => {
  const documents = Array.from({ length: 50 }, (_, i) => ({
    documentId: `d${i}`,
    title: `Document ${i}`,
    slug: `d${i}`,
    publishedAt: published,
  }));
  const usefulLinks = documents.map((doc) => ({
    label: doc.title,
    href: `/${doc.slug}`,
  }));
  const settings = {
    publishedAt: published,
    documents: [...documents].reverse(),
    usefulLinks,
  };
  assert.equal(
    (await readFooter(settings, documents)).ctx.body.data.documents.length,
    50,
  );
  assert.deepEqual(
    (await readFooter(settings, documents)).ctx.body.data.usefulLinks,
    usefulLinks,
  );
  settings.documents = [documents[20], documents[1]];
  settings.usefulLinks = [usefulLinks[3], usefulLinks[0]];
  const { ctx } = await readFooter(settings, documents);
  assert.deepEqual(
    ctx.body.data.documents.map((link) => link.href),
    ["/documents/d20", "/documents/d1"],
  );
  assert.deepEqual(ctx.body.data.usefulLinks, settings.usefulLinks);
});

const unsafe = [
  "javascript:alert(1)",
  "data:text/html,x",
  "//evil.example",
  "/\\evil.example",
  "https:\\evil.example",
  "\nhttps://evil.example",
  "/\tevil",
  " https://example.org",
  "https://exa mple.org",
  "mailto:a@example.org",
  "https://",
  "relative",
  "",
  null,
  42,
];
const safe = [
  "/",
  "/documents/privacy-policy",
  "/about?x=1#details",
  "https://example.org/path?q=1",
  "http://example.org",
  "HTTPS://пример.рф/path",
  "/with%20space",
];

test("footer filters unsafe links on read while preserving safe addresses and order", async () => {
  const { ctx } = await readFooter({
    publishedAt: published,
    usefulLinks: [...unsafe, ...safe]
      .map((href) => ({ label: "Link", href }))
      .concat([{ href: "/no-label" }, { label: "", href: "/empty-label" }]),
  });
  assert.deepEqual(
    ctx.body.data.usefulLinks,
    safe.map((href) => ({ label: "Link", href })),
  );
});

test("footer URL validation is registered on Document Service writes", async () => {
  let middleware;
  app.register({
    strapi: {
      documents: {
        use(fn) {
          middleware = fn;
        },
      },
    },
  });
  assert.equal(typeof middleware, "function");
  for (const action of ["create", "update"]) {
    for (const href of unsafe) {
      let called = false;
      await assert.rejects(
        () =>
          middleware(
            {
              uid: footerUid,
              action,
              params: { data: { usefulLinks: [{ label: "Link", href }] } },
            },
            async () => {
              called = true;
            },
          ),
        { name: "ValidationError" },
      );
      assert.equal(called, false);
    }
    for (const href of safe) {
      assert.equal(
        await middleware(
          {
            uid: footerUid,
            action,
            params: { data: { usefulLinks: [{ label: "Link", href }] } },
          },
          async () => "saved",
        ),
        "saved",
      );
    }
  }
  for (const context of [
    {
      uid: documentUid,
      action: "update",
      params: { data: { usefulLinks: [{ href: "javascript:x" }] } },
    },
    { uid: footerUid, action: "update", params: { data: { documents: [] } } },
    { uid: footerUid, action: "findFirst", params: {} },
  ])
    assert.equal(
      await middleware(context, async () => "unchanged"),
      "unchanged",
    );
});

test("footer projection is list-only and creates no public write route", async () => {
  const ctx = {
    params: { kind: "footer", slug: "anything" },
    notFound() {
      this.status = 404;
    },
  };
  await controller.one(ctx);
  assert.equal(ctx.status, 404);
  const { routes } = require("../src/api/public-content/routes/public-content");
  assert.ok(routes.every((route) => route.method === "GET"));
});
