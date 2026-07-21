// Fetcher centralizzato: tutte le chiamate passano da /api/* (rewrite Next → backend FastAPI)

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

async function handle<T>(res: Response): Promise<T> {
  if (res.status === 401 && typeof window !== "undefined") {
    // Sessione scaduta: il proxy autentica di nuovo via Authentik.
    window.location.href = `/login?callbackUrl=${encodeURIComponent(window.location.pathname)}`;
  }
  if (!res.ok) {
    let detail = `Errore HTTP ${res.status}`;
    try {
      const body: unknown = await res.json();
      if (body && typeof body === "object" && "detail" in body) {
        const d = (body as { detail: unknown }).detail;
        detail = typeof d === "string" ? d : JSON.stringify(d);
      }
    } catch {
      // body non-JSON: si tiene il messaggio generico
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

const JSON_HEADERS = { "Content-Type": "application/json" };

export const api = {
  get<T>(path: string): Promise<T> {
    return fetch(`/api${path}`, { cache: "no-store" }).then((r) => handle<T>(r));
  },
  post<T>(path: string, body?: unknown): Promise<T> {
    return fetch(`/api${path}`, {
      method: "POST",
      headers: body !== undefined ? JSON_HEADERS : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    }).then((r) => handle<T>(r));
  },
  put<T>(path: string, body: unknown): Promise<T> {
    return fetch(`/api${path}`, {
      method: "PUT",
      headers: JSON_HEADERS,
      body: JSON.stringify(body),
    }).then((r) => handle<T>(r));
  },
  del<T>(path: string): Promise<T> {
    return fetch(`/api${path}`, { method: "DELETE" }).then((r) => handle<T>(r));
  },
};

export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.detail;
  if (err instanceof Error) return err.message;
  return "Errore sconosciuto";
}
