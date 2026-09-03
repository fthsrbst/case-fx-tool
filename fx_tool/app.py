"""HTTP layer: one endpoint, one error shape. Everything else lives in service.py."""

from __future__ import annotations

from contextlib import asynccontextmanager
from decimal import Decimal

import httpx
from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from fx_tool.config import Settings, load_settings
from fx_tool.errors import ConversionError
from fx_tool.service import Conversion, Converter, ecb_today
from fx_tool.upstream import UpstreamClient


def create_app(
    settings: Settings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    clock=ecb_today,
) -> FastAPI:
    """`transport` and `clock` exist so tests can fake the upstream and freeze today."""
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        upstream = UpstreamClient(settings.upstream_base, settings.upstream_timeout_seconds, transport)
        app.state.converter = Converter(settings, upstream, clock=clock)
        try:
            yield
        finally:
            await upstream.aclose()

    app = FastAPI(title="fx-tool", version="0.1.0", lifespan=lifespan)

    @app.exception_handler(ConversionError)
    async def conversion_error(_: Request, exc: ConversionError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content={"error": exc.code, "message": exc.message})

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"error": "invalid_request", "message": str(exc)})

    @app.get("/tools/convert")
    async def convert(
        request: Request,
        amount: str | None = Query(None, description="Amount to convert, e.g. 250 or 19.99"),
        from_: str | None = Query(None, alias="from", description="Source currency, ISO 4217, e.g. EUR"),
        to: str | None = Query(None, description="Target currency, ISO 4217, e.g. TRY"),
        date: str | None = Query(None, description="YYYY-MM-DD; defaults to today (Frankfurt time)"),
    ) -> JSONResponse:
        converter: Converter = request.app.state.converter
        conversion = await converter.convert(amount, from_, to, date)
        return JSONResponse(status_code=200, content=_body(conversion))

    return app


def _number(value: Decimal) -> int | float:
    return int(value) if value == value.to_integral_value() else float(value)


def _body(c: Conversion) -> dict:
    body = {
        "amount": _number(c.amount),
        "from": c.base,
        "to": c.target,
        "rate": _number(c.rate),
        "result": _number(c.result),
        "rate_date": c.rate_date.isoformat(),
        "asked_date": c.asked_date.isoformat(),
        "source": "ECB via frankfurter.dev",
        "rate_is_fallback": c.is_fallback,
    }
    if c.is_fallback:
        body["note"] = (
            f"No ECB rate was published for {c.asked_date.isoformat()}; "
            f"this is the most recent earlier rate, from {c.rate_date.isoformat()}."
        )
    return body


app = create_app()
