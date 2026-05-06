"""HTTP API for manual trading workflows and log streaming."""

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
        allowed = getattr(scheduler.config, "cors_allowed_origins", None)
        self.cors_allowed_origins: tuple[str, ...] = (
            tuple(allowed) if isinstance(allowed, (list, tuple)) else ()
        )


class TradingApiRequestHandler(BaseHTTPRequestHandler):
    """Handle manual trading workflow endpoints."""

    server: TradingApiServer

    def do_GET(self) -> None:  # noqa: N802
        parsed_url = urlparse(self.path)
        path = parsed_url.path.rstrip("/") or "/"

        if path == "/":
            self._send_json(
                HTTPStatus.OK,
                {"status": "ok", "service": "trading-backend"},
            )
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
            "/api/report/quarterly": ("quarterly_report", self.server.scheduler.run_manual_quarterly_report),
            "/api/report/biannual": ("biannual_report", self.server.scheduler.run_manual_biannual_report),
            "/api/report/annual": ("annual_report", self.server.scheduler.run_manual_annual_report),
            "/api/scheduler/reset": ("scheduler_reset", self.server.scheduler.reset_locks),
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

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self._write_cors_headers()
        requested_headers = self.headers.get("Access-Control-Request-Headers", "")
        self.send_header(
            "Access-Control-Allow-Headers",
            requested_headers or "Content-Type, Accept",
        )
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Max-Age", "86400")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        self.server.logger.info("%s - %s", self.address_string(), format % args)

    def _resolve_allowed_origin(self) -> str | None:
        origin = self.headers.get("Origin")
        if not origin:
            return None
        allowed = self.server.cors_allowed_origins
        if not allowed:
            return None
        if "*" in allowed:
            return "*"
        if origin in allowed:
            return origin
        return None

    def _write_cors_headers(self) -> None:
        allowed_origin = self._resolve_allowed_origin()
        if allowed_origin is None:
            return
        self.send_header("Access-Control-Allow-Origin", allowed_origin)
        if allowed_origin != "*":
            self.send_header("Vary", "Origin")

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=True, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._write_cors_headers()
        self.end_headers()
        self.wfile.write(body)

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
        self._write_cors_headers()
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
