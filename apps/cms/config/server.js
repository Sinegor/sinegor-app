module.exports = ({ env }) => ({
  host: env("HOST", "127.0.0.1"),
  port: env.int("PORT", 1337),
  url: env("CMS_PUBLIC_ORIGIN", "http://localhost:1337"),
  // Enable only behind the private, header-replacing production reverse proxy.
  proxy: { koa: env.bool("CMS_BEHIND_PROXY", false), maxIpsCount: 1 },
  app: { keys: env.array("APP_KEYS") },
});
