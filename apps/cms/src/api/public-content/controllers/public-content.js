const types = {
  pages: "api::page.page",
  services: "api::service.service",
  publications: "api::publication.publication",
};
const media = (file) =>
  file
    ? {
        url: file.url,
        alternativeText: file.alternativeText || "",
        mime: file.mime,
      }
    : null;
const clean = (item) => ({
  slug: item.slug,
  title: item.title,
  summary: item.summary,
  publishedAt: item.publishedAt,
  sections: (item.sections || []).map((s) => ({
    heading: s.heading,
    text: s.text,
  })),
  seo: item.seo
    ? { title: item.seo.title, description: item.seo.description }
    : null,
  image: media(item.image),
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
  const fields = ["slug", "title", "summary", "publishedAt"];
  const populate = { sections: true, seo: true, image: true };
  if (ctx.params.kind === "pages") {
    Object.assign(populate, { video: true });
    fields.push("videoCaption", "contactEmail", "contactPhone");
  }
  const offset = Math.max(0, Number.parseInt(ctx.query.offset, 10) || 0);
  const data = await strapi
    .documents(uid)
    .findMany({
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
  ctx.body = {
    data: single ? clean(data[0]) : data.map(clean),
    nextOffset: !single && data.length === 25 ? offset + 25 : null,
  };
}
module.exports = {
  list: (ctx) => get(ctx, false),
  one: (ctx) => get(ctx, true),
};
