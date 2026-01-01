"""Reusable base classes for web UI servers."""
from __future__ import annotations

import json
import signal
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, Optional


class BaseRequestHandler(SimpleHTTPRequestHandler):
    """Base request handler with common JSON API handling."""

    def __init__(self, *args, directory: str, **kwargs) -> None:
        """Initialize handler with directory."""
        super().__init__(*args, directory=directory, **kwargs)

    def do_POST(self) -> None:  # pragma: no cover - exercised manually
        """Route POST requests to _handle_api."""
        endpoint = self.path.rstrip("/")
        if endpoint.startswith("/api/"):
            # Read and parse JSON payload
            length = int(self.headers.get("Content-Length", "0"))
            payload = self.rfile.read(length).decode("utf-8") if length else "{}"
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                self.send_error(400, "Invalid JSON")
                return

            # Delegate to subclass implementation
            try:
                self._handle_api(endpoint, data)
            except NotImplementedError:
                self.send_error(404, "Unknown endpoint")
        else:
            self.send_error(404, "Unknown endpoint")

    def _handle_api(self, endpoint: str, data: Dict[str, Any]) -> None:
        """Handle API endpoints. Subclasses must override this method.

        Args:
            endpoint: The API endpoint path (e.g., "/api/decision")
            data: Parsed JSON request data

        Raises:
            NotImplementedError: If endpoint is not recognized
        """
        raise NotImplementedError("Subclasses must implement _handle_api")

    def _read_payload(self) -> Dict[str, Any]:
        """Read and parse JSON payload from request body.

        Returns:
            Parsed JSON data, or empty dict if parsing fails.
        """
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    def _write_json(self, data: Dict[str, Any], status: int = 200) -> None:
        """Write JSON response.

        Args:
            data: Data to serialize as JSON
            status: HTTP status code (default: 200)
        """
        encoded = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args) -> None:  # pragma: no cover
        """Silence default logging."""
        return


class BaseWebServer:
    """Base web server wrapper with common setup and lifecycle management."""

    def __init__(
        self,
        handler_factory: Callable[..., BaseRequestHandler],
        host: str = "127.0.0.1",
        port: int = 0,
    ) -> None:
        """Initialize server.

        Args:
            handler_factory: Factory function/partial that creates request handler instances
            host: Host to bind to (default: 127.0.0.1)
            port: Port to bind to (default: 0 for ephemeral port)
        """
        self.server = ThreadingHTTPServer((host, port), handler_factory)
        self.thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start server in background thread."""
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def wait_forever(self) -> None:
        """Wait for server to be interrupted (Ctrl+C) and shut down gracefully."""
        try:
            signal.pause()
        except AttributeError:
            # Windows does not have pause(); fall back to sleep loop
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
        except KeyboardInterrupt:
            pass
        finally:
            self.server.shutdown()

    @property
    def address(self) -> tuple[str, int]:
        """Get server address as (host, port) tuple."""
        return self.server.server_address

    @property
    def port(self) -> int:
        """Get server port."""
        return self.server.server_address[1]

    @property
    def url(self) -> str:
        """Get base server URL."""
        host, port = self.server.server_address
        return f"http://{host}:{port}"
