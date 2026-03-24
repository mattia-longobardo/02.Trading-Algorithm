"""HTTP API and live log dashboard for manual trading workflows."""

from __future__ import annotations

import json
import logging
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from scheduler import JobExecutionLockedError, TradingScheduler

LOG_DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Trading Bot Logs</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #0f172a;
      --panel: #111827;
      --line: #1f2937;
      --text: #e5e7eb;
      --muted: #94a3b8;
      --accent: #22c55e;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      background: radial-gradient(circle at top, #1e293b 0%, var(--bg) 45%);
      color: var(--text);
    }
    main {
      max-width: 1200px;
      margin: 0 auto;
      padding: 24px;
    }
    .header {
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: center;
      margin-bottom: 16px;
      flex-wrap: wrap;
    }
    .title {
      margin: 0;
      font-size: 28px;
    }
    .subtitle {
      margin: 6px 0 0;
      color: var(--muted);
      font-size: 14px;
    }
    .status {
      color: var(--muted);
      font-size: 13px;
    }
    .log-panel {
      border: 1px solid var(--line);
      background: rgba(17, 24, 39, 0.92);
      border-radius: 14px;
      overflow: hidden;
      box-shadow: 0 20px 45px rgba(0, 0, 0, 0.25);
    }
    .toolbar {
      display: flex;
      gap: 12px;
      align-items: center;
      justify-content: space-between;
      padding: 12px 16px;
      border-bottom: 1px solid var(--line);
      background: rgba(15, 23, 42, 0.95);
      flex-wrap: wrap;
    }
    .pill {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      color: var(--muted);
      font-size: 13px;
    }
    .dot {
      width: 10px;
      height: 10px;
      border-radius: 999px;
      background: var(--accent);
      box-shadow: 0 0 12px rgba(34, 197, 94, 0.8);
    }
    pre {
      margin: 0;
      padding: 16px;
      min-height: 70vh;
      max-height: 70vh;
      overflow: auto;
      white-space: pre-wrap;
      word-break: break-word;
      line-height: 1.45;
      font-size: 13px;
    }
  </style>
</head>
<body>
  <main>
    <div class="header">
      <div>
        <h1 class="title">Trading Bot Logs</h1>
        <p class="subtitle">Live tail del file di log del bot</p>
      </div>
      <div class="status" id="status">Connecting...</div>
    </div>
    <section class="log-panel">
      <div class="toolbar">
        <div class="pill"><span class="dot"></span> Streaming live delle nuove righe</div>
        <div class="pill" id="meta">Loading...</div>
      </div>
      <pre id="logs">Loading logs...</pre>
    </section>
  </main>
  <script>
    const logsEl = document.getElementById("logs");
    const statusEl = document.getElementById("status");
    const metaEl = document.getElementById("meta");

    function appendChunk(chunk) {
      if (!chunk) {
        return;
      }
      const stickToBottom = logsEl.scrollTop + logsEl.clientHeight >= logsEl.scrollHeight - 20;
      if (logsEl.textContent === "Loading logs...") {
        logsEl.textContent = chunk;
      } else {
        logsEl.textContent += chunk;
      }
      if (stickToBottom) {
        logsEl.scrollTop = logsEl.scrollHeight;
      }
    }

    async function loadInitialLogs() {
      try {
        const response = await fetch("/api/logs?lines=10000", { cache: "no-store" });
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        const payload = await response.json();
        logsEl.textContent = payload.logs || "No logs available.";
        metaEl.textContent = `${payload.line_count} lines from ${payload.log_file}`;
        statusEl.textContent = `Connected: ${payload.updated_at}`;
        logsEl.scrollTop = logsEl.scrollHeight;
      } catch (error) {
        statusEl.textContent = `Initial load failed: ${error.message}`;
      }
    }

    function connectStream() {
      const events = new EventSource("/api/logs/stream");
      events.onopen = () => {
        statusEl.textContent = "Streaming connected";
      };
      events.addEventListener("append", (event) => {
        appendChunk(event.data);
      });
      events.addEventListener("heartbeat", (event) => {
        statusEl.textContent = `Streaming live: ${event.data}`;
      });
      events.onerror = () => {
        statusEl.textContent = "Streaming reconnecting...";
      };
    }

    loadInitialLogs().then(connectStream);
  </script>
</body>
</html>
"""


class TradingApiServer(ThreadingHTTPServer):
    """HTTP server carrying shared scheduler and logger dependencies."""

    def __init__(
        self,
        server_address: tuple[str, int],
        scheduler: TradingScheduler,
        logger: logging.Logger,
    ) -> None:
        super().__init__(server_address, TradingApiRequestHandler)
        self.scheduler = scheduler
        self.logger = logger.getChild("api")


class TradingApiRequestHandler(BaseHTTPRequestHandler):
    """Handle manual trading workflow endpoints."""

    server: TradingApiServer

    def do_GET(self) -> None:  # noqa: N802
        parsed_url = urlparse(self.path)
        path = parsed_url.path.rstrip("/") or "/"

        if path == "/":
            self._send_html(HTTPStatus.OK, LOG_DASHBOARD_HTML)
            return

        if path == "/api/logs":
            query = parse_qs(parsed_url.query)
            requested_lines = query.get("lines", ["10000"])[0]
            self._handle_logs_endpoint(requested_lines)
            return

        if path == "/api/logs/stream":
            self._handle_logs_stream()
            return

        routes: dict[str, tuple[str, Any]] = {
            "/api/universe/generate": ("universe", self.server.scheduler.run_manual_refresh_universe),
            "/api/orders/generate": ("new_orders", self.server.scheduler.run_manual_generate_new_orders),
            "/api/report/generate": ("report", self.server.scheduler.run_manual_weekly_report),
        }

        route = routes.get(path)
        if route is None:
            self._send_json(
                HTTPStatus.NOT_FOUND,
                {"error": "not_found", "message": f"Unsupported path: {path}"},
            )
            return

        action, handler = route
        try:
            handler()
        except JobExecutionLockedError as exc:
            self.server.logger.warning("Manual API request for %s skipped: %s", action, exc)
            self._send_json(
                HTTPStatus.CONFLICT,
                {"status": "error", "action": action, "message": str(exc)},
            )
            return
        except Exception:
            self.server.logger.exception("Manual API request for %s failed", action)
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"status": "error", "action": action, "message": f"Failed to start {action} job"},
            )
            return

        self._send_json(
            HTTPStatus.OK,
            {
                "status": "ok",
                "action": action,
                "message": f"{action} job completed successfully",
            },
        )

    def log_message(self, format: str, *args: object) -> None:
        self.server.logger.info("%s - %s", self.address_string(), format % args)

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=True, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, status: HTTPStatus, body: str) -> None:
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _handle_logs_endpoint(self, requested_lines: str) -> None:
        try:
            line_count = max(1, min(int(requested_lines), 10000))
        except ValueError:
            line_count = 10000

        log_path = Path(self.server.scheduler.config.log_file)
        payload = {
            "log_file": str(log_path),
            "line_count": line_count,
            "logs": self._tail_log_file(log_path, line_count),
            "updated_at": self.date_time_string(log_path.stat().st_mtime) if log_path.exists() else "N/A",
        }
        self._send_json(HTTPStatus.OK, payload)

    def _handle_logs_stream(self) -> None:
        log_path = Path(self.server.scheduler.config.log_file)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        self._write_sse_event("heartbeat", self.date_time_string())
        if not log_path.exists():
            self._write_sse_event("append", "Log file not found.\n")

        position = log_path.stat().st_size if log_path.exists() else 0
        last_heartbeat = time.monotonic()

        try:
            while True:
                if log_path.exists():
                    current_size = log_path.stat().st_size
                    if current_size < position:
                        position = 0

                    if current_size > position:
                        with log_path.open("r", encoding="utf-8", errors="replace") as handle:
                            handle.seek(position)
                            chunk = handle.read()
                            position = handle.tell()
                        if chunk:
                            self._write_sse_event("append", chunk)

                now = time.monotonic()
                if now - last_heartbeat >= 1:
                    self._write_sse_event("heartbeat", self.date_time_string())
                    last_heartbeat = now

                time.sleep(1)
        except (BrokenPipeError, ConnectionResetError):
            self.server.logger.debug("Log stream client disconnected")

    def _write_sse_event(self, event_name: str, data: str) -> None:
        payload_lines = data.splitlines() or [""]
        message = [f"event: {event_name}"]
        for line in payload_lines:
            message.append(f"data: {line}")
        message.append("")
        message.append("")
        self.wfile.write("\n".join(message).encode("utf-8"))
        self.wfile.flush()

    @staticmethod
    def _tail_log_file(log_path: Path, line_count: int) -> str:
        if not log_path.exists():
            return "Log file not found."

        try:
            with log_path.open("r", encoding="utf-8", errors="replace") as handle:
                lines = handle.readlines()[-line_count:]
        except OSError as exc:
            return f"Failed to read log file: {exc}"
        return "".join(lines)


def create_api_server(host: str, port: int, scheduler: TradingScheduler, logger: logging.Logger) -> TradingApiServer:
    """Create the HTTP server exposing manual trading endpoints."""

    return TradingApiServer((host, port), scheduler, logger)
