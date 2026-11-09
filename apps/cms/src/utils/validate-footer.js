const {
  errors: { ValidationError },
} = require("@strapi/utils");
const { isSafeFooterHref } = require("./footer-links");

module.exports = async function validateFooter(context, next) {
  if (
    context.uid === "api::footer-settings.footer-settings" &&
    ["create", "update"].includes(context.action) &&
    Array.isArray(context.params.data?.usefulLinks)
  ) {
    for (const [index, link] of context.params.data.usefulLinks.entries()) {
      if (!isSafeFooterHref(link?.href)) {
        throw new ValidationError(
          "Укажите путь сайта, начинающийся с /, или полный HTTP(S)-адрес без пробелов и обратных слешей.",
          {
            errors: [
              {
                path: ["usefulLinks", index, "href"],
                name: "ValidationError",
                message: "Недопустимый адрес ссылки",
              },
            ],
          },
        );
      }
    }
  }
  return next();
};
