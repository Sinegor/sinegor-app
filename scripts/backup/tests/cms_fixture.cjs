// Real Strapi Document/Upload services against disposable fixture databases only.
const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert/strict");
const { createRequire } = require("node:module");
const cmsRequire = createRequire(path.join(process.cwd(), "package.json"));
const { createStrapi } = cmsRequire("@strapi/strapi");
const sharp = cmsRequire("sharp");
const privateDir = process.env.SINEGOR_BACKUP_PRIVATE;
const uid = "api::public-document.public-document";

async function main() {
  const app = await createStrapi().load();
  try {
    if (process.argv[2] === "seed") {
      const pdf = path.join(privateDir, "synthetic.pdf");
      const [uploaded] = await app
        .plugin("upload")
        .service("upload")
        .upload({
          data: {},
          files: {
            filepath: pdf,
            originalFilename: "synthetic.pdf",
            mimetype: "application/pdf",
            size: fs.statSync(pdf).size,
          },
        });
      const png = path.join(privateDir, "synthetic.png");
      await sharp({
        create: {
          width: 1200,
          height: 800,
          channels: 3,
          background: "#33aa77",
        },
      })
        .png()
        .toFile(png);
      const [image] = await app
        .plugin("upload")
        .service("upload")
        .upload({
          data: {},
          files: {
            filepath: png,
            originalFilename: "synthetic.png",
            mimetype: "image/png",
            size: fs.statSync(png).size,
          },
        });
      assert(Object.keys(image.formats).length > 0);
      const document = await app.documents(uid).create({
        status: "published",
        data: {
          title: "Synthetic restore fixture",
          slug: "backup-fixture",
          revisedOn: "2026-11-04",
          pdf: uploaded.id,
          body: [
            {
              type: "paragraph",
              children: [{ type: "text", text: "Synthetic fixture" }],
            },
          ],
        },
      });
      await app.documents("api::page.page").create({
        status: "published",
        data: {
          title: "Synthetic media fixture",
          slug: "backup-media",
          image: image.id,
        },
      });
      fs.writeFileSync(
        path.join(privateDir, "cms-expected.json"),
        JSON.stringify({
          documentId: document.documentId,
          pdfUrl: uploaded.url,
          imageUrl: image.url,
          formats: image.formats,
        }),
      );
    } else {
      const expected = JSON.parse(
        fs.readFileSync(path.join(privateDir, "cms-expected.json")),
      );
      const document = await app.documents(uid).findOne({
        documentId: expected.documentId,
        status: "published",
        populate: { pdf: true },
      });
      assert.equal(document.slug, "backup-fixture");
      assert.equal(document.body[0].children[0].text, "Synthetic fixture");
      assert.equal(document.pdf.url, expected.pdfUrl);
      const pages = await app.documents("api::page.page").findMany({
        filters: { slug: "backup-media" },
        status: "published",
        populate: { image: true },
      });
      assert.equal(pages[0].image.url, expected.imageUrl);
      assert.deepEqual(pages[0].image.formats, expected.formats);
      for (const url of [
        document.pdf.url,
        expected.imageUrl,
        ...Object.values(expected.formats).map((item) => item.url),
      ]) {
        assert(fs.existsSync(path.join(process.cwd(), "public", url)));
      }
      const controller = require(
        path.join(
          process.cwd(),
          "src/api/public-content/controllers/public-content.js",
        ),
      );
      const ctx = {
        params: { kind: "documents", slug: "backup-fixture" },
        query: {},
        set() {},
        notFound() {
          throw new Error("Restored publication missing");
        },
      };
      await controller.one(ctx);
      assert.equal(ctx.body.data.pdf.url, expected.pdfUrl);
    }
  } finally {
    await app.destroy();
  }
}
main().catch((error) => {
  console.error("CMS fixture failed:", error.name, error.code || "validation");
  process.exitCode = 1;
});
