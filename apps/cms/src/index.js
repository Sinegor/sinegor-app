module.exports = {
  register({ strapi }) {
    strapi.documents.use(require("./utils/validate-footer"));
  },
  async bootstrap({ strapi }) {
    // Public registration is unrelated to content editing and stays disabled.
    const store = strapi.store({ type: "plugin", name: "users-permissions" });
    const advanced = await store.get({ key: "advanced" });
    await store.set({
      key: "advanced",
      value: { ...advanced, allow_register: false },
    });
  },
};
