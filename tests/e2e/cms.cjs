// Test-data management through real Strapi document/upload services, never public API stubs.
const fs = require("node:fs");
const path = require("node:path");
const http = require("node:http");
const config = JSON.parse(fs.readFileSync(process.env.SINEGOR_E2E_CONFIG));
const { createStrapi } = require(
  path.join(config.workspace, "apps/cms/node_modules/@strapi/strapi"),
);
(async () => {
  const app = await createStrapi().load();
  for (const { kind, data } of require(
    path.join(config.workspace, "apps/cms/scripts/f4-content.json"),
  )) {
    await app
      .documents(kind === "pages" ? "api::page.page" : "api::service.service")
      .create({ data, status: "published" });
  }
  await app.documents("api::publication.publication").create({
    status: "published",
    data: {
      slug: "e2e-stable-article",
      title: "E2E опубликованный материал",
      sections: [{ text: "Публичный материал из Strapi" }],
    },
  });
  await app.start();
  http
    .createServer(async (request, response) => {
      if (
        request.headers["x-e2e-key"] !== config.control_key ||
        request.method !== "POST"
      ) {
        response.writeHead(403);
        response.end();
        return;
      }
      try {
        let raw = "";
        for await (const part of request) raw += part;
        const payload = JSON.parse(raw),
          docs = app.documents(
            {
              pages: "api::page.page",
              services: "api::service.service",
              publications: "api::publication.publication",
            }[payload.kind || "publications"],
          );
        let result;
        if (payload.action === "create")
          result = await docs.create({ status: "draft", data: payload.data });
        else if (payload.action === "update")
          result = await docs.update({
            documentId: payload.id,
            data: payload.data,
          });
        else if (["publish", "unpublish"].includes(payload.action))
          result = await docs[payload.action]({ documentId: payload.id });
        else if (payload.action === "media") {
          const file = path.join(
            config.workspace,
            "apps/web/public/media/sinegor-lab-preview.jpg",
          );
          const [uploaded] = await app
            .plugin("upload")
            .service("upload")
            .upload({
              data: {},
              files: {
                filepath: file,
                originalFilename: "e2e.jpg",
                mimetype: "image/jpeg",
                size: fs.statSync(file).size,
              },
            });
          const page = await app.documents("api::page.page").create({
            status: "published",
            data: {
              slug: payload.slug || "e2e-media",
              title: "E2E медиа",
              image: uploaded.id,
              sections: [{ text: "Публичное медиа" }],
            },
          });
          result = {
            url: uploaded.url,
            id: page.documentId,
            mediaId: uploaded.id,
          };
        } else {
          response.writeHead(400);
          response.end();
          return;
        }
        response.writeHead(200, { "Content-Type": "application/json" });
        response.end(JSON.stringify(result));
      } catch {
        response.writeHead(500);
        response.end("Fixture data operation failed");
      }
    })
    .listen(config.ports.cms_control, "127.0.0.1");
})().catch(() => {
  console.error("E2E CMS startup failed");
  process.exitCode = 1;
});
