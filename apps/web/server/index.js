import path from "node:path";
import { performance } from "node:perf_hooks";

// Set the mode before loading React Router and its SSR build.
process.env.NODE_ENV ??= "production";
const [
  { default: express },
  { default: compression },
  { createRequestHandler },
  { matchRoutes },
  build,
] = await Promise.all([
  import("express"),
  import("compression"),
  import("@react-router/express"),
  import("react-router"),
  import("../build/server/index.js"),
]);

// Use only trusted manifest paths in logs. Never interpolate matched params.
const manifest = Object.values(build.routes);
function children(parentId) {
  return manifest
    .filter((route) => route.parentId === parentId)
    .map((route) => ({
      id: route.id,
      path: route.path,
      index: route.index,
      caseSensitive: route.caseSensitive,
      children: children(route.id),
    }));
}
const routes = children(undefined);
const manifestPath = path.posix.join(
  build.basename,
  build.routeDiscovery.manifestPath,
);
function safePath(pathname) {
  if (pathname.startsWith("/assets/")) return "/assets/*";
  if (pathname.startsWith("/media/")) return "/media/*";
  if (pathname === manifestPath) return manifestPath;
  const routePath = build.future.v8_trailingSlashAwareDataRequests
    ? (pathname.endsWith("/_.data")
        ? pathname.replace(/_\.data$/, "")
        : pathname.replace(/\.data$/, "")) || "/"
    : pathname === path.posix.join(build.basename, "_root.data")
      ? build.basename
      : pathname.replace(/\.data$/, "") || "/";
  const matches = matchRoutes(routes, routePath, build.basename);
  return matches
    ? path.posix.join(
        build.basename,
        ...matches.map((match) => match.route.path ?? ""),
      )
    : "/:unmatched";
}
const methods = new Set([
  "GET",
  "HEAD",
  "POST",
  "PUT",
  "PATCH",
  "DELETE",
  "OPTIONS",
]);
const app = express();
app.disable("x-powered-by");
app.use((req, res, next) => {
  const started = performance.now();
  const method = methods.has(req.method) ? req.method : "OTHER";
  let template = "/:unmatched";
  let recorded = false;
  const record = () => {
    if (recorded) return;
    recorded = true;
    process.stdout.write(
      JSON.stringify({
        event: "http_access",
        method,
        path: template,
        status: res.headersSent ? res.statusCode : 499,
        aborted: !res.writableFinished,
        duration_ms: Number((performance.now() - started).toFixed(3)),
      }) + "\n",
    );
  };
  res.once("finish", record);
  res.once("close", record);
  // React Router warns with the raw path if percent decoding fails.
  try {
    // URL normalization must precede discovery validation, including /x/../__manifest.
    const url = new URL(`http://ssr.invalid${req.originalUrl}`);
    decodeURIComponent(url.pathname);
    template = safePath(url.pathname);
    // Discovery treats query `paths` as route paths and decodes them again.
    if (url.pathname === manifestPath) {
      decodeURIComponent(url.searchParams.get("paths") ?? "");
    }
  } catch {
    res.status(400).type("text/plain").send("Bad Request");
    return;
  }
  next();
});
app.use(compression());
app.use(
  path.posix.join(build.publicPath, "assets"),
  express.static(path.join(build.assetsBuildDirectory, "assets"), {
    immutable: true,
    maxAge: "1y",
  }),
);
app.use(build.publicPath, express.static(build.assetsBuildDirectory));
app.use(express.static("public", { maxAge: "1h" }));
app.all("*", createRequestHandler({ build, mode: process.env.NODE_ENV }));
// Do not delegate to Express's default logger: exception text may contain URLs.
app.use((_error, _req, res, _next) => {
  process.stderr.write(
    JSON.stringify({ event: "ssr_adapter_error", status: 500 }) + "\n",
  );
  if (res.headersSent) res.destroy();
  else res.status(500).type("text/plain").send("Internal Server Error");
});
const server = app.listen(
  Number(process.env.PORT ?? 3000),
  process.env.HOST,
  () => {
    process.stdout.write(
      JSON.stringify({ event: "ssr_listening", port: server.address().port }) +
        "\n",
    );
  },
);
server.on("error", () => {
  process.stderr.write(JSON.stringify({ event: "ssr_start_failed" }) + "\n");
  process.exitCode = 1;
});
for (const signal of ["SIGTERM", "SIGINT"]) {
  process.once(signal, () => server.close());
}
