/**
 * Generic backend proxy.
 *
 * Every browser API call hits `/api/proxy/<original-backend-path>`; this
 * handler rewrites it to `BACKEND_INTERNAL_URL/<original-backend-path>` and
 * forwards method, headers, body and cookies. The browser never sees the
 * backend host directly, so:
 *
 *   - the backend can sit on the private `trading_internal` Docker network
 *     and stay off `proxy_public`;
 *   - the auth cookie is scoped to a single origin (the frontend host);
 *   - CORS is a non-issue because every request is same-origin from the
 *     browser's point of view.
 *
 * Server-Sent Events (`/api/logs/stream`) are forwarded as a streaming
 * response with the original `text/event-stream` content type intact.
 */

import { NextRequest } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const BACKEND_BASE = (process.env.BACKEND_INTERNAL_URL ?? "http://backend:8000").replace(/\/$/, "");

// Headers we strip on the way in/out — they describe the hop, not the message.
const HOP_BY_HOP = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
  "host",
  "content-length",
]);

function copyHeaders(source: Headers): Headers {
  const out = new Headers();
  source.forEach((value, key) => {
    if (HOP_BY_HOP.has(key.toLowerCase())) return;
    out.set(key, value);
  });
  return out;
}

async function forward(request: NextRequest, path: string[]): Promise<Response> {
  const url = new URL(request.url);
  const target = `${BACKEND_BASE}/${path.join("/")}${url.search}`;

  const init: RequestInit = {
    method: request.method,
    headers: copyHeaders(request.headers),
    redirect: "manual",
  };

  if (!["GET", "HEAD"].includes(request.method)) {
    const body = await request.arrayBuffer();
    if (body.byteLength > 0) {
      init.body = body;
    }
  }

  let upstream: Response;
  try {
    upstream = await fetch(target, init);
  } catch (err) {
    return new Response(
      JSON.stringify({
        error: {
          code: "upstream_unreachable",
          message: `Backend unreachable: ${err instanceof Error ? err.message : String(err)}`,
        },
      }),
      { status: 502, headers: { "Content-Type": "application/json" } }
    );
  }

  // Stream the body back so SSE works without buffering.
  const responseHeaders = copyHeaders(upstream.headers);
  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: responseHeaders,
  });
}

type RouteContext = { params: Promise<{ path: string[] }> };

export async function GET(request: NextRequest, ctx: RouteContext) {
  const { path } = await ctx.params;
  return forward(request, path);
}

export async function POST(request: NextRequest, ctx: RouteContext) {
  const { path } = await ctx.params;
  return forward(request, path);
}

export async function PATCH(request: NextRequest, ctx: RouteContext) {
  const { path } = await ctx.params;
  return forward(request, path);
}

export async function PUT(request: NextRequest, ctx: RouteContext) {
  const { path } = await ctx.params;
  return forward(request, path);
}

export async function DELETE(request: NextRequest, ctx: RouteContext) {
  const { path } = await ctx.params;
  return forward(request, path);
}

export async function OPTIONS(request: NextRequest, ctx: RouteContext) {
  const { path } = await ctx.params;
  return forward(request, path);
}
