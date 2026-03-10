from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .error_codes import ErrorCode
from .exceptions import AppException


def register_exception_handlers(app):

    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "detail": exc.message,
                "error_code": exc.error_code,
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = exc.errors()
        first_msg = errors[0].get("msg", "Invalid input.") if errors else "Invalid input."

        return JSONResponse(
            status_code=422,
            content={
                "detail": first_msg,
                "error_code": ErrorCode.INVALID_INPUT,
                "errors": [
                    {
                        "field": " -> ".join(str(loc) for loc in error.get("loc", [])),
                        "message": error.get("msg"),
                    }
                    for error in errors
                ],
            },
        )
