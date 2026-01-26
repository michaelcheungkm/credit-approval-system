export async function onRequest(context: any) {
  const url = new URL(context.request.url);

  // Set this in Cloudflare Pages environment variables:
  // - Local dev: WORKER_BASE_URL=http://localhost:8787
  // - Prod:      WORKER_BASE_URL=https://<your-worker>.workers.dev
  const workerBase =
    (context.env?.WORKER_BASE_URL as string | undefined) ?? "http://localhost:8787";

  // Proxy `/api/*` to the worker, preserving the remainder of the path and query.
  const upstream = new URL(workerBase.replace(/\/$/, "") + url.pathname);
  upstream.search = url.search;

  // Forward request method/headers/body. This keeps auth headers if you add them later.
  const req = new Request(upstream.toString(), context.request);
  return fetch(req);
}
