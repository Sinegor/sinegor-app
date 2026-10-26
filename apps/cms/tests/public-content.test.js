const { test } = require("node:test");
const assert = require("node:assert/strict");
const controller = require("../src/api/public-content/controllers/public-content");

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
            text: "Исходный текст",
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
    assert.equal(data.sections[0].text, "Исходный текст");
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

test("legacy text and images survive without new settings or nested media", async () => {
  const { data } = await read({
    slug: "legacy",
    image,
    sections: [{ text: "Первый" }, { text: "Второй" }],
  });
  assert.equal(data.image.url, image.url);
  assert.equal(data.imageLayout, null);
  assert.deepEqual(data.sections, [
    { text: "Первый", heading: undefined, image: null, imageLayout: null },
    { text: "Второй", heading: undefined, image: null, imageLayout: null },
  ]);
});
