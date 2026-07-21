import { auth } from "@/auth";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://trading-backend:8000";

async function forward(request: Request, context: { params: Promise<{ path: string[] }> }) {
  const session = await auth();
  if (!session?.user) {
    return Response.json({ detail: "Non autenticato" }, { status: 401 });
  }

  const { path } = await context.params;
  const incoming = new URL(request.url);
  const target = new URL(`/${path.map(encodeURIComponent).join("/")}`, BACKEND_URL);
  target.search = incoming.search;

  const headers = new Headers();
  const contentType = request.headers.get("content-type");
  const accept = request.headers.get("accept");
  if (contentType) headers.set("content-type", contentType);
  if (accept) headers.set("accept", accept);

  const user = session.user as typeof session.user & { id?: string };
  headers.set("x-trading-user-id", user.id ?? user.email ?? "unknown");
  if (user.email) headers.set("x-trading-user-email", user.email);
  if (user.name) headers.set("x-trading-user-name", user.name);

  const hasBody = request.method !== "GET" && request.method !== "HEAD";
  const upstream = await fetch(target, {
    method: request.method,
    headers,
    body: hasBody ? await request.arrayBuffer() : undefined,
    cache: "no-store",
  });

  const responseHeaders = new Headers();
  for (const key of ["content-type", "content-disposition", "cache-control"]) {
    const value = upstream.headers.get(key);
    if (value) responseHeaders.set(key, value);
  }
  return new Response(upstream.body, {
    status: upstream.status,
    headers: responseHeaders,
  });
}

export const GET = forward;
export const POST = forward;
export const PUT = forward;
export const PATCH = forward;
export const DELETE = forward;
