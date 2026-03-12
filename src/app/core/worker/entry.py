import uvloop  # noqa: I001
uvloop.install()

import asyncio
import http.server
import os
import threading

from arq.cli import run_worker

from app.core.worker.settings import WorkerSettings


class _HealthHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass


def _start_health_server() -> None:
    port = int(os.environ.get("PORT", 8080))
    server = http.server.HTTPServer(("0.0.0.0", port), _HealthHandler)
    server.serve_forever()


if __name__ == "__main__":
    health_thread = threading.Thread(target=_start_health_server, daemon=True)
    health_thread.start()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    run_worker(WorkerSettings)
