module.exports = {
  routes: [
    {
      method: "GET",
      path: "/public-content/:kind",
      handler: "public-content.list",
      config: { auth: false },
    },
    {
      method: "GET",
      path: "/public-content/:kind/:slug",
      handler: "public-content.one",
      config: { auth: false },
    },
  ],
};
