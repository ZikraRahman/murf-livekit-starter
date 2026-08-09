"""Small localhost API used by the frontend's server-side memory proxy."""

from __future__ import annotations

import json
import logging
import os
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from memory import delete_memory_fact, delete_user, get_user, init_db

logger = logging.getLogger(__name__)


class MemoryHandler(BaseHTTPRequestHandler):
    def _authorized_user_id(self) -> str | None:
        expected_secret = os.getenv("LIVEKIT_API_SECRET")
        if expected_secret and self.headers.get("X-Memory-Secret") != expected_secret:
            return None
        return self.headers.get("X-Memory-User-Id")

    def _json(self, status: HTTPStatus, body: object) -> None:
        encoded = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:  # noqa: N802
        user_id = self._authorized_user_id()
        if not user_id:
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "Unauthorized"})
            return
        self._json(HTTPStatus.OK, {"memory": get_user(user_id)})

    def do_DELETE(self) -> None:  # noqa: N802
        user_id = self._authorized_user_id()
        if not user_id:
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "Unauthorized"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "Invalid JSON"})
            return
        if payload.get("all") is True:
            deleted = delete_user(user_id)
        elif isinstance(payload.get("key"), str):
            deleted = delete_memory_fact(user_id, payload["key"])
        else:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "Specify a memory key or all"})
            return
        self._json(HTTPStatus.OK, {"deleted": deleted})

    def log_message(self, format: str, *args: object) -> None:
        return


def create_server() -> ThreadingHTTPServer:
    init_db()
    port = int(os.getenv("MEMORY_API_PORT", "8001"))
    return ThreadingHTTPServer(("127.0.0.1", port), MemoryHandler)


def start_in_background() -> None:
    """Start the local service when the agent is launched without start_app.*."""
    try:
        server = create_server()
    except OSError as error:
        logger.info("Memory API was not started: %s", error)
        return
    threading.Thread(target=server.serve_forever, daemon=True, name="memory-api").start()
    logger.info("Memory API listening on http://127.0.0.1:%s", server.server_port)


def main() -> None:
    create_server().serve_forever()


if __name__ == "__main__":
    main()
