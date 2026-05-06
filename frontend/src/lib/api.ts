export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://localhost:8000";

export type JobAction =
  | "universe"
  | "new_orders"
  | "report"
  | "quarterly_report"
  | "biannual_report"
  | "annual_report"
  | "scheduler_reset";

export interface JobResponse {
  status: "ok" | "error";
  action?: JobAction;
  message: string;
}

export interface LogsResponse {
  log_file: string;
  line_count: number;
  logs: string;
  updated_at: string;
}

export async function triggerJob(path: string): Promise<JobResponse> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "GET",
    cache: "no-store",
  });
  const payload = (await response.json()) as JobResponse;
  if (!response.ok) {
    throw Object.assign(new Error(payload.message ?? `HTTP ${response.status}`), {
      payload,
      status: response.status,
    });
  }
  return payload;
}

export async function fetchLogs(lines: number = 10000): Promise<LogsResponse> {
  const response = await fetch(`${API_BASE_URL}/api/logs?lines=${lines}`, {
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`Failed to fetch logs: HTTP ${response.status}`);
  }
  return (await response.json()) as LogsResponse;
}

export function logsStreamUrl(): string {
  return `${API_BASE_URL}/api/logs/stream`;
}
