"""The only place that talks to frankfurter.dev (or whatever FX_UPSTREAM_BASE points at)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

import httpx

from fx_tool import errors

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class PublishedRate:
    base: str
    target: str
    rate: Decimal
    # The day this rate actually belongs to, as stated by the upstream itself.
    published_on: date


class UpstreamClient:
    def __init__(self, base_url: str, timeout_seconds: float, transport: httpx.AsyncBaseTransport | None = None):
        self._timeout = timeout_seconds
        self._client = httpx.AsyncClient(
            base_url=f"{base_url}/v1",
            timeout=timeout_seconds,
            transport=transport,
            headers={"User-Agent": "fx-tool/0.1"},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def rate_on(self, base: str, target: str, on: date) -> PublishedRate:
        """Ask for the rate on a day. Frankfurter answers with the newest rate at or
        before that day and says which day it is from; we pass that on untouched."""
        try:
            response = await self._client.get(f"/{on.isoformat()}", params={"base": base, "symbols": target})
        except httpx.TimeoutException:
            raise errors.upstream_timeout(self._timeout)
        except httpx.HTTPError as exc:
            raise errors.upstream_unavailable(type(exc).__name__)

        if response.status_code == 404:
            raise errors.unknown_currency(base, target)
        if response.status_code >= 400:
            raise errors.upstream_error(response.status_code)

        try:
            payload = response.json(parse_float=Decimal, parse_int=Decimal)
        except (ValueError, InvalidOperation):
            raise errors.upstream_invalid("body is not JSON")
        return _parse(payload, base, target)


def _parse(payload: object, base: str, target: str) -> PublishedRate:
    if not isinstance(payload, dict):
        raise errors.upstream_invalid("body is not a JSON object")

    published = payload.get("date")
    if not isinstance(published, str) or not _DATE_RE.match(published):
        raise errors.upstream_invalid("missing or malformed 'date'")
    try:
        published_on = date.fromisoformat(published)
    except ValueError:
        raise errors.upstream_invalid(f"impossible date {published!r}")

    if payload.get("base") != base:
        raise errors.upstream_invalid(f"answered for base {payload.get('base')!r}, not {base}")

    rates = payload.get("rates")
    if not isinstance(rates, dict) or target not in rates:
        raise errors.upstream_invalid(f"no rate for {target} in the answer")
    raw = rates[target]
    if isinstance(raw, bool) or not isinstance(raw, (Decimal, int, float, str)):
        raise errors.upstream_invalid(f"rate for {target} is not a number")
    if len(str(raw)) > 96:
        raise errors.upstream_invalid("rate exceeds the supported numeric precision")
    try:
        rate = Decimal(str(raw))
    except InvalidOperation:
        raise errors.upstream_invalid(f"rate for {target} is not a number")
    if not rate.is_finite() or rate <= 0:
        raise errors.upstream_invalid(f"rate for {target} is {raw!r}")
    # Bound untrusted numeric data so multiplication and cent rounding fit in
    # the service's 64-digit context, without silently rounding the rate itself.
    if not Decimal("1e-24") <= rate <= Decimal("1e24") or len(rate.as_tuple().digits) > 36:
        raise errors.upstream_invalid("rate must be between 1e-24 and 1e24 with at most 36 significant digits")

    return PublishedRate(base=base, target=target, rate=rate, published_on=published_on)
