import uvloop  # noqa: I001
uvloop.install()

import asyncio

from arq.cli import run_worker

from app.core.worker.settings import WorkerSettings

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    run_worker(WorkerSettings)
