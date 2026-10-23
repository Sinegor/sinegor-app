// Transparent shared-origin proxy. No endpoint responses are fabricated.
const fs = require("node:fs");
const http = require("node:http");
const config = JSON.parse(fs.readFileSync(process.env.SINEGOR_E2E_CONFIG));
http
  .createServer((request, response) => {
    const port = request.url.startsWith("/api/")
      ? config.ports.api
      : config.ports.web;
    const upstream = http.request(
      {
        hostname: "127.0.0.1",
        port,
        path: request.url,
        method: request.method,
        headers: request.headers,
      },
      (reply) => {
        response.writeHead(reply.statusCode, reply.headers);
        reply.pipe(response);
      },
    );
    upstream.on("error", () => {
      response.writeHead(503);
      response.end("Service unavailable");
    });
    request.pipe(upstream);
  })
  .listen(config.ports.proxy, "localhost");
