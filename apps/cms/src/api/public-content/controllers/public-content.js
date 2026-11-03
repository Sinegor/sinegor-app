const types = {
  pages: "api::page.page",
  services: "api::service.service",
  publications: "api::publication.publication",
  documents: "api::public-document.public-document",
};
const media = (file) =>
  file
    ? {
        url: file.url,
        alternativeText: file.alternativeText || "",
        mime: file.mime,
        width: file.width,
        height: file.height,
      }
    : null;
const imageLayout = (layout) =>
  layout
    ? {
        position: ["top", "left", "right"].includes(layout.position)
          ? layout.position
          : "top",
        size: ["small", "medium", "large", "full"].includes(layout.size)
          ? layout.size
          : "medium",
        alignment: ["left", "center", "right"].includes(layout.alignment)
          ? layout.alignment
          : "center",
        caption: typeof layout.caption === "string" ? layout.caption : "",
      }
    : null;
const clean = (item) => ({
  slug: item.slug,
  title: item.title,
  summary: item.summary,
  publishedAt: item.publishedAt,
  linkSection: item.linkSection,
  linkOrder: item.linkOrder,
  sections: (item.sections || []).map((s) => ({
    heading: s.heading,
    general: Array.isArray(s.general) ? s.general : [],
    image: media(s.image),
    imageLayout: imageLayout(s.imageLayout),
  })),
  seo: item.seo
    ? {
        title: item.seo.title,
        description: item.seo.description,
        noindex: item.seo.noindex === true,
      }
    : null,
  image: media(item.image),
  imageLayout: imageLayout(item.imageLayout),
  video: media(item.video),
  videoCaption: item.videoCaption,
  contactEmail: item.contactEmail,
  contactPhone: item.contactPhone,
});
async function get(ctx, single) {
  const uid = Object.hasOwn(types, ctx.params.kind)
    ? types[ctx.params.kind]
    : null;
  if (!uid) return ctx.notFound();
  const isDocument = ctx.params.kind === "documents";
  const fields = isDocument
    ? ["slug", "title", "body", "revisedOn", "publishedAt"]
    : ["slug", "title", "summary", "publishedAt"];
  const populate = isDocument
    ? { seo: true, pdf: true }
    : {
        sections: { populate: { image: true, imageLayout: true } },
        seo: true,
        image: true,
        imageLayout: true,
      };
  if (ctx.params.kind === "pages") {
    Object.assign(populate, { video: true });
    fields.push(
      "videoCaption",
      "contactEmail",
      "contactPhone",
      "linkSection",
      "linkOrder",
    );
  }
  const offset = Math.max(0, Number.parseInt(ctx.query.offset, 10) || 0);
  const data = await strapi.documents(uid).findMany({
    status: "published",
    fields,
    populate,
    filters: single ? { slug: ctx.params.slug } : {},
    sort: ["publishedAt:desc", "slug:asc"],
    start: single ? 0 : offset,
    limit: single ? 1 : 25,
  });
  ctx.set("Cache-Control", "no-store");
  if (single && !data.length) return ctx.notFound();
  const serialize = (item) =>
    isDocument
      ? {
          slug: item.slug,
          title: item.title,
          publishedAt: item.publishedAt,
          body: Array.isArray(item.body) ? item.body : [],
          revisedOn: item.revisedOn,
          pdf: item.pdf?.mime === "application/pdf" ? media(item.pdf) : null,
          seo: clean(item).seo,
        }
      : clean(item);
  ctx.body = {
    data: single ? serialize(data[0]) : data.map(serialize),
    nextOffset: !single && data.length === 25 ? offset + 25 : null,
  };
}
module.exports = {
  list: (ctx) => get(ctx, false),
  one: (ctx) => get(ctx, true),
};
