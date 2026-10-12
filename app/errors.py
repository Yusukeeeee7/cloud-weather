from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.cities import City
from app.schemas import ErrorDetail, ErrorResponse


class UpstreamError(Exception):
    """外部APIの呼び出しに失敗した、または応答が想定の形でなかった。"""


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    body = ErrorResponse(error=ErrorDetail(code=code, message=message))
    return JSONResponse(status_code=status_code, content=body.model_dump())


async def _handle_validation_error(request: Request, exc: Exception) -> JSONResponse:
    # 入力は city だけなので、検証エラーはすべて invalid_city。入力値は応答に含めない。
    allowed = ", ".join(city.value for city in City)
    return _error_response(422, "invalid_city", f"city must be one of: {allowed}")


async def _handle_upstream_error(request: Request, exc: Exception) -> JSONResponse:
    # 外部の URL や例外の文面は応答に出さない（詳細はログに残す）。
    return _error_response(502, "upstream_error", "weather provider is unavailable")


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(UpstreamError, _handle_upstream_error)
