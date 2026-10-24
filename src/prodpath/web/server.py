"""Standard-library HTTP server: static single-page UI plus a small JSON API (ADR-019)."""

from __future__ import annotations

import json
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from prodpath.providers.aws.pricing import PriceError, update_prices
from prodpath.web.bundle import build_bundle, build_zip
from prodpath.web.github import RepoError
from prodpath.web.jobs import STAGES, JobError, JobManager

STATIC_DIR = Path(__file__).parent / "static"
SAMPLE_DIR = Path(__file__).parent / "sample"
MAX_BODY_BYTES = 64 * 1024
LOOPBACK = {"127.0.0.1", "::1", "localhost"}
ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/favicon.svg": ("favicon.svg", "image/svg+xml"),
}
# Inline script and style are refused: repo-derived text can never run as code (SECURITY.md 3b).
CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)
_JOB = re.compile(r"^/api/jobs/([A-Za-z0-9_-]{6,40})$")
_RUN = re.compile(r"^/api/runs/([A-Za-z0-9_-]{6,40})$")
_RUN_FORECAST = re.compile(r"^/api/runs/([A-Za-z0-9_-]{6,40})/forecast$")
_RUN_ZIP = re.compile(r"^/api/runs/([A-Za-z0-9_-]{6,40})/download\.zip$")
_REGION = re.compile(r"^[a-z]{2}(-[a-z]+)+-\d$")


class Handler(BaseHTTPRequestHandler):
    server_version = "prodpath"
    sys_version = ""

    @property
    def manager(self) -> JobManager:
        return self.server.manager  # type: ignore[attr-defined,no-any-return]

    # -- plumbing --------------------------------------------------------------------------
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - signature is fixed
        return  # request lines can carry repo URLs; keep the console quiet

    def _headers(self, status: int, content_type: str, length: int, cache: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", cache)
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.end_headers()

    def _json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self._headers(status, "application/json; charset=utf-8", len(body), "no-store")
        self.wfile.write(body)

    def _error(self, status: int, message: str) -> None:
        self._json({"error": message}, status)

    def _host_ok(self) -> bool:
        """Block DNS-rebinding when bound to loopback: the Host header must be a loopback name."""
        if self.server.allow_public:  # type: ignore[attr-defined]
            return True
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
        return host in LOOPBACK

    def _body(self) -> dict[str, Any] | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if not 0 < length <= MAX_BODY_BYTES:
            self._error(HTTPStatus.BAD_REQUEST, "Send a small JSON body.")
            return None
        try:
            data = json.loads(self.rfile.read(length))
        except (ValueError, UnicodeDecodeError):
            self._error(HTTPStatus.BAD_REQUEST, "The request body is not valid JSON.")
            return None
        if not isinstance(data, dict):
            self._error(HTTPStatus.BAD_REQUEST, "The request body must be a JSON object.")
            return None
        return data

    # -- routes ----------------------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        if not self._host_ok():
            return self._error(HTTPStatus.FORBIDDEN, "Unexpected Host header.")
        path = self.path.split("?", 1)[0]
        if path in ASSETS:
            return self._asset(*ASSETS[path])
        if path == "/api/health":
            return self._json({"ok": True, "stages": list(STAGES)})
        if match := _JOB.match(path):
            return self._job(match[1])
        if match := _RUN.match(path):
            run = self.manager.run(match[1])
            if run is None:
                return self._error(
                    HTTPStatus.NOT_FOUND, "That result has expired or never existed."
                )
            return self._json(build_bundle(run, match[1]))
        if match := _RUN_ZIP.match(path):
            return self._zip(match[1])
        self._error(HTTPStatus.NOT_FOUND, "Not found.")

    def do_POST(self) -> None:  # noqa: N802
        if not self._host_ok():
            return self._error(HTTPStatus.FORBIDDEN, "Unexpected Host header.")
        if "application/json" not in (self.headers.get("Content-Type") or ""):
            return self._error(
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Use Content-Type: application/json."
            )
        data = self._body()
        if data is None:
            return
        path = self.path.split("?", 1)[0]
        try:
            if path == "/api/analyze":
                return self._analyze(data)
            if match := _RUN_FORECAST.match(path):
                run = self.manager.whatif(match[1], data)
                return self._json(build_bundle(run, match[1]))
            if path == "/api/prices/update":
                return self._prices(data)
        except (RepoError, JobError) as error:
            return self._error(HTTPStatus.BAD_REQUEST, str(error))
        self._error(HTTPStatus.NOT_FOUND, "Not found.")

    def _asset(self, name: str, content_type: str) -> None:
        file = STATIC_DIR / name
        if not file.is_file():
            return self._error(HTTPStatus.NOT_FOUND, "Not found.")
        body = file.read_bytes()
        self._headers(HTTPStatus.OK, content_type, len(body), "no-cache")
        self.wfile.write(body)

    def _analyze(self, data: dict[str, Any]) -> None:
        url = data.get("url")
        options = data.get("options", {})
        if not isinstance(url, str) or not isinstance(options, dict):
            raise JobError('Send {"url": "https://github.com/owner/repo"}.')
        job = self.manager.submit(self.client_address[0], url, options)
        self._json({"job_id": job.id}, HTTPStatus.ACCEPTED)

    def _job(self, job_id: str) -> None:
        job = self.manager.job(job_id)
        if job is None:
            return self._error(HTTPStatus.NOT_FOUND, "That job has expired or never existed.")
        self._json(
            {
                "status": job.status,
                "stage": job.stage,
                "stages": list(STAGES),
                "log": job.log,
                "error": job.error,
            }
        )

    def _zip(self, run_id: str) -> None:
        run = self.manager.run(run_id)
        if run is None:
            return self._error(HTTPStatus.NOT_FOUND, "That result has expired or never existed.")
        body = build_zip(run)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Disposition", 'attachment; filename="prodpath-output.zip"')
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _prices(self, data: dict[str, Any]) -> None:
        """Networked (public AWS Price List); only the machine running the server may trigger it."""
        if self.client_address[0] not in LOOPBACK:
            return self._error(HTTPStatus.FORBIDDEN, "Only the server's own machine may do this.")
        region = data.get("region", "ap-south-1")
        if not isinstance(region, str) or not _REGION.match(region):
            return self._error(HTTPStatus.BAD_REQUEST, "That is not an AWS region name.")
        try:
            update_prices(region, self.manager.price_dir)
        except PriceError as error:
            return self._error(HTTPStatus.BAD_GATEWAY, str(error))
        self._json({"ok": True, "region": region})


def make_server(
    manager: JobManager, host: str = "127.0.0.1", port: int = 8765, allow_public: bool = False
) -> ThreadingHTTPServer:
    if host not in LOOPBACK and not allow_public:
        raise ValueError(
            "refusing to listen on a public address: put a TLS and authentication proxy in front "
            "and pass --allow-public (docs/SECURITY.md section 3b)"
        )
    server = ThreadingHTTPServer((host, port), Handler)
    server.manager = manager  # type: ignore[attr-defined]
    server.allow_public = allow_public  # type: ignore[attr-defined]
    return server
