from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from uuid6 import uuid7

from .api import router
from .core.config import settings
from .core.exceptions.authorization_exceptions import ForbiddenError
from .core.exceptions.db_exceptions import NonTransientDatabaseError, TransientDatabaseError
from .core.exceptions.domain_exceptions import InvalidInputError, NotFoundError
from .core.setup import create_application, lifespan_factory
from .core.utils.qdrant_cloud import init_collections


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    init_collections()

    default_lifespan = lifespan_factory(settings)
    async with default_lifespan(app):
        yield


app = create_application(router=router, settings=settings, lifespan=lifespan)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request.state.request_id = str(uuid7())
    return await call_next(request)


@app.exception_handler(ForbiddenError)
async def forbidden_error_handler(request: Request, error: ForbiddenError) -> JSONResponse:
    return JSONResponse(status_code=403, content={"detail": str(error)})


@app.exception_handler(NotFoundError)
async def not_found_error_handler(request: Request, error: NotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(error)})


@app.exception_handler(InvalidInputError)
async def invalid_input_error_handler(request: Request, error: InvalidInputError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(error)})


@app.exception_handler(TransientDatabaseError)
async def transient_db_error_handler(request: Request, error: TransientDatabaseError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(error)})


@app.exception_handler(NonTransientDatabaseError)
async def non_transient_db_error_handler(request: Request, error: NonTransientDatabaseError) -> JSONResponse:
    return JSONResponse(status_code=500, content={"detail": str(error)})
