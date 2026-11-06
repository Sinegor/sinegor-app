import { PassThrough } from "node:stream";
import { createReadableStreamFromReadable } from "@react-router/node";
import {
  ServerRouter,
  isRouteErrorResponse,
  type EntryContext,
  type HandleErrorFunction,
} from "react-router";
import { renderToPipeableStream } from "react-dom/server";

export default function handleRequest(
  request: Request,
  status: number,
  headers: Headers,
  context: EntryContext,
) {
  headers.set("Content-Type", "text/html; charset=utf-8");
  headers.set("Referrer-Policy", "no-referrer");
  headers.set("Cache-Control", "no-store");
  headers.set("X-Content-Type-Options", "nosniff");
  return new Promise<Response>((resolve, reject) => {
    let timer: ReturnType<typeof setTimeout>;
    const { pipe, abort } = renderToPipeableStream(
      <ServerRouter context={context} url={request.url} />,
      {
        onAllReady() {
          clearTimeout(timer);
          const body = new PassThrough();
          resolve(
            new Response(createReadableStreamFromReadable(body), {
              status,
              headers,
            }),
          );
          pipe(body);
        },
        onShellError(error: unknown) {
          clearTimeout(timer);
          reject(error);
        },
        onError() {
          status = 500;
        },
      },
    );
    timer = setTimeout(abort, 5000);
  });
}

// Error messages, stacks and route params can contain user input.
export const handleError: HandleErrorFunction = (error, { request }) => {
  if (request.signal.aborted) return;
  console.error(
    JSON.stringify({
      event: "ssr_error",
      status: isRouteErrorResponse(error) ? error.status : 500,
    }),
  );
};
