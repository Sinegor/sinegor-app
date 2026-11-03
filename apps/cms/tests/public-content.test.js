const { test } = require("node:test");
const assert = require("node:assert/strict");
const controller = require("../src/api/public-content/controllers/public-content");

test("preserves current Blocks for every public collection and handles empty sections", async () => {
  const general = [
    {
      type: "paragraph",
      children: [{ type: "text", text: "Current content", bold: true }],
    },
  ];
  for (const kind of ["pages", "services", "publications"]) {
    const { data } = await read(
      { slug: "blocks", sections: [{ general }, { general: null }, {}] },
      kind,
    );
    assert.deepEqual(data.sections[0].general, general);
    assert.deepEqual(data.sections[1].general, []);
    assert.deepEqual(data.sections[2].general, []);
  }
});

// The document service is the DB boundary; exercise the real public serializer.
async function read(item, kind = "pages") {
  let query;
  global.strapi = {
    documents: () => ({
      findMany: async (options) => {
        query = options;
        return [item];
      },
    }),
  };
  const ctx = {
    params: { kind, slug: item.slug },
    query: { status: "draft" },
    set() {},
    notFound() {
      throw new Error("Unexpected 404");
    },
  };
  try {
    await controller.one(ctx);
    return { data: ctx.body.data, query };
  } finally {
    delete global.strapi;
  }
}

const image = {
  id: 17,
  url: "/uploads/illustration.png",
  alternativeText: "Иллюстрация",
  mime: "image/png",
  width: 1600,
  height: 900,
  provider_metadata: { private: "must not be exposed" },
};
const layout = {
  position: "right",
  size: "small",
  alignment: "left",
  caption: "Подпись <script>text</script>",
  id: 42,
  style: "position:fixed",
};

test("exposes root and section image presentation without internal media fields", async () => {
  for (const kind of ["pages", "services", "publications"]) {
    const { data, query } = await read(
      {
        slug: "existing",
        title: "Существующий материал",
        image,
        imageLayout: layout,
        sections: [
          {
            heading: "Раздел",
            general: [
              {
                type: "paragraph",
                children: [{ type: "text", text: "Исходный текст" }],
              },
            ],
            image,
            imageLayout: layout,
          },
        ],
      },
      kind,
    );
    assert.deepEqual(data.image, {
      url: image.url,
      alternativeText: image.alternativeText,
      mime: image.mime,
      width: 1600,
      height: 900,
    });
    assert.deepEqual(data.sections[0].image, data.image);
    assert.deepEqual(data.imageLayout, {
      position: "right",
      size: "small",
      alignment: "left",
      caption: layout.caption,
    });
    assert.deepEqual(data.sections[0].imageLayout, data.imageLayout);
    assert.equal(
      data.sections[0].general[0].children[0].text,
      "Исходный текст",
    );
    assert.equal(query.status, "published");
    assert.deepEqual(query.populate.sections, {
      populate: { image: true, imageLayout: true },
    });
    assert.equal(query.populate.imageLayout, true);
  }
});

test("invalid layout values use safe defaults and unknown fields are omitted", async () => {
  const { data } = await read({
    slug: "invalid",
    imageLayout: {
      position: "fixed",
      size: "99999px",
      alignment: "__proto__",
      caption: 5,
    },
  });
  assert.deepEqual(data.imageLayout, {
    position: "top",
    size: "medium",
    alignment: "center",
    caption: "",
  });
});

test("optional Blocks and images survive without settings or nested media", async () => {
  const { data } = await read({
    slug: "legacy",
    image,
    sections: [{ general: null }, {}],
  });
  assert.equal(data.image.url, image.url);
  assert.equal(data.imageLayout, null);
  assert.deepEqual(data.sections, [
    { general: [], heading: undefined, image: null, imageLayout: null },
    { general: [], heading: undefined, image: null, imageLayout: null },
  ]);
});

test("public SEO exposes noindex and keeps legacy content indexable", async () => {
  const hidden = await read({ slug: "hidden", seo: { noindex: true } });
  assert.equal(hidden.data.seo.noindex, true);
  const legacy = await read({ slug: "legacy", seo: { title: "Existing SEO" } });
  assert.equal(legacy.data.seo.noindex, false);
});

test("public pages expose managed link placement and order", async () => {
  const { data, query } = await read({
    slug: "guide",
    linkSection: "technical",
    linkOrder: 2,
  });
  assert.equal(data.linkSection, "technical");
  assert.equal(data.linkOrder, 2);
  assert.ok(query.fields.includes("linkSection"));
  assert.ok(query.fields.includes("linkOrder"));
});

test("public documents use published-only queries and expose Blocks, revision and PDF", async () => {
  const body = [
    { type: "paragraph", children: [{ type: "text", text: "Test content" }] },
  ];
  const { data, query } = await read(
    {
      slug: "privacy-policy",
      title: "Test document",
      body,
      revisedOn: "2026-11-02",
      pdf: { ...image, url: "/uploads/document.pdf", mime: "application/pdf" },
      privateAgreement: "must not be exposed",
    },
    "documents",
  );
  assert.equal(query.status, "published");
  assert.deepEqual(query.populate, { seo: true, pdf: true });
  assert.ok(query.fields.includes("body"));
  assert.deepEqual(data.body, body);
  assert.equal(data.revisedOn, "2026-11-02");
  assert.equal(data.pdf.url, "/uploads/document.pdf");
  assert.equal(data.privateAgreement, undefined);
  assert.equal(data.pdf.provider_metadata, undefined);
});

test("public documents omit attachments that are not PDFs", async () => {
  const { data } = await read(
    { slug: "service-rules", pdf: image },
    "documents",
  );
  assert.equal(data.pdf, null);
});
