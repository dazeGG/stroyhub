from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict


class ApiErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    details: dict[str, Any] = {}


class ApiError(Exception):
    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = ApiErrorResponse(
            code=code,
            message=message,
            details=details or {},
        )


@dataclass(frozen=True)
class ValueErrorRule:
    message: str
    status_code: int
    code: str


def value_error_mapper(
    rules: tuple[ValueErrorRule, ...],
    *,
    default_status_code: int = 400,
    default_code: str = "invalid_request",
) -> Callable[[ValueError], ApiError]:
    by_message = {rule.message: rule for rule in rules}

    def _convert(error: ValueError) -> ApiError:
        detail = str(error)
        rule = by_message.get(detail)
        if rule is None:
            return ApiError(
                status_code=default_status_code,
                code=default_code,
                message=detail,
            )
        return ApiError(
            status_code=rule.status_code,
            code=rule.code,
            message=detail,
        )

    return _convert


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _handle_api_error(_: Request, error: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            content=error.payload.model_dump(),
        )


def api_error_responses(*status_codes: int) -> dict[int | str, dict[str, Any]]:
    responses: dict[int | str, dict[str, Any]] = {}
    for status_code in status_codes:
        if status_code == 422:
            responses[status_code] = {
                "description": "Validation error or typed API error",
                "content": {
                    "application/json": {
                        "schema": {
                            "oneOf": [
                                {"$ref": "#/components/schemas/HTTPValidationError"},
                                {"$ref": "#/components/schemas/ApiErrorResponse"},
                            ]
                        }
                    }
                },
            }
            continue
        responses[status_code] = {
            "model": ApiErrorResponse,
            "description": f"Error {status_code}",
        }
    return responses
