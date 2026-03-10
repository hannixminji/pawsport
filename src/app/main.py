import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import firebase_admin
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from uuid6 import uuid7

from .api import router
from .core.config import settings
from .core.exception_handlers import register_exception_handlers
from .core.setup import create_application, lifespan_factory
from .core.utils.qdrant_cloud import init_collections

LOGGER = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    if not firebase_admin._apps:
        firebase_admin.initialize_app()

    init_collections()

    default_lifespan = lifespan_factory(settings)
    async with default_lifespan(app):
        yield


app = create_application(router=router, settings=settings, lifespan=lifespan)

register_exception_handlers(app)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request.state.request_id = str(uuid7())
    return await call_next(request)


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, error: Exception) -> JSONResponse:
    LOGGER.exception("Unhandled exception on request %s", request.state.request_id)
    return JSONResponse(status_code=500, content={"detail": "An unexpected error occurred. Please try again later."})
