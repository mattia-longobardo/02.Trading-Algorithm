/**
 * Browser-side API client. Every call goes through the Next.js Route Handler
 * proxy at `/api/proxy/*`, which forwards to the backend over the internal
 * Docker network. The browser never talks to the backend directly.
 */

const API_PREFIX = "/api/proxy";

export class ApiError extends Error {
  status: number;
  code: string | null;
  payload: unknown;

  constructor(message: string, status: number, code: string | null, payload: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.payload = payload;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_PREFIX}${path}`, {
    cache: "no-store",
    credentials: "same-origin",
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });

  const text = await response.text();
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = text;
    }
  }

  if (!response.ok) {
    const errorBlock = (payload as { error?: { message?: string; code?: string } } | null)?.error;
    const detail = (payload as { detail?: { error?: { message?: string; code?: string } } } | null)?.detail
      ?.error;
    const error = errorBlock ?? detail ?? null;
    const message = error?.message ?? `HTTP ${response.status}`;
    throw new ApiError(message, response.status, error?.code ?? null, payload);
  }

  return payload as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path, { method: "GET" }),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body !== undefined ? JSON.stringify(body) : undefined }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PATCH", body: body !== undefined ? JSON.stringify(body) : undefined }),
  delete: <T>(path: string) => request<T>(path, { method: "DELETE" }),
};

export function streamUrl(path: string): string {
  return `${API_PREFIX}${path}`;
}
