"""Input validation, the date policy, the cache, and the arithmetic. No HTTP here."""

from __future__ import annotations

import re
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from fx_tool import errors
from fx_tool.config import Settings
from fx_tool.upstream import PublishedRate, UpstreamClient

# The euro reference rates begin here; nothing earlier exists.
SERIES_START = date(1999, 1, 4)
# The ECB publishes in Frankfurt; "today" and "future" follow its calendar.
ECB_TZ = ZoneInfo("Europe/Berlin")

_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_MAX_AMOUNT = Decimal("1000000000000")  # 1e12: nobody converts more in one call
_MAX_AMOUNT_DIGITS = 24
_CENT = Decimal("0.01")


@dataclass(frozen=True)
class Conversion:
    amount: Decimal
    base: str
    target: str
    rate: Decimal
    result: Decimal
    rate_date: date
    asked_date: date

    @property
    def is_fallback(self) -> bool:
        return self.rate_date != self.asked_date


@dataclass(frozen=True)
class Request:
    amount: Decimal
    base: str
    target: str
    asked_date: date


def parse_request(amount: str | None, base: str | None, target: str | None, on: str | None, today: date) -> Request:
    return Request(
        amount=_parse_amount(amount),
        base=_parse_currency(base, "from"),
        target=_parse_currency(target, "to"),
        asked_date=_parse_date(on, today),
    )


def _parse_amount(raw: str | None) -> Decimal:
    if raw is None or raw.strip() == "":
        raise errors.invalid_amount("'amount' is required.")
    text = raw.strip()
    if len(text) > _MAX_AMOUNT_DIGITS:
        raise errors.invalid_amount(f"'amount' has too many digits (max {_MAX_AMOUNT_DIGITS}).")
    try:
        amount = Decimal(text)
    except InvalidOperation:
        raise errors.invalid_amount(f"'amount' must be a decimal number, got {raw!r}.")
    if not amount.is_finite():
        raise errors.invalid_amount(f"'amount' must be a finite number, got {raw!r}.")
    if amount <= 0:
        raise errors.invalid_amount("'amount' must be greater than zero.")
    if amount > _MAX_AMOUNT:
        raise errors.invalid_amount(f"'amount' must be at most {_MAX_AMOUNT:f}.")
    return amount


def _parse_currency(raw: str | None, name: str) -> str:
    if raw is None or raw.strip() == "":
        raise errors.ConversionError(400, "invalid_currency", f"'{name}' is required.")
    code = raw.strip().upper()
    if not _CURRENCY_RE.match(code):
        raise errors.invalid_currency(raw)
    return code


def _parse_date(raw: str | None, today: date) -> date:
    if raw is None or raw.strip() == "":
        return today
    text = raw.strip()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", text):
        raise errors.invalid_date(raw)
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise errors.invalid_date(raw)


def ecb_today() -> date:
    return datetime.now(ECB_TZ).date()


class Converter:
    def __init__(self, settings: Settings, upstream: UpstreamClient, clock=ecb_today, monotonic=time.monotonic):
        self._settings = settings
        self._upstream = upstream
        self._today = clock
        self._now = monotonic
        # key -> (rate, expires_at or None for "never")
        self._cache: OrderedDict[tuple[str, str, date], tuple[PublishedRate, float | None]] = OrderedDict()

    async def convert(self, amount: str | None, base: str | None, target: str | None, on: str | None) -> Conversion:
        today = self._today()
        req = parse_request(amount, base, target, on, today)

        if req.base == req.target:
            raise errors.same_currency(req.base)
        if req.asked_date > today:
            raise errors.date_in_future(req.asked_date.isoformat(), today.isoformat())
        if req.asked_date < SERIES_START:
            raise errors.date_before_series(req.asked_date.isoformat(), SERIES_START.isoformat())

        published = await self._published_rate(req, today)

        # The upstream may only ever hand us a rate from the asked day or earlier.
        gap = (req.asked_date - published.published_on).days
        if gap < 0:
            raise errors.upstream_invalid(
                f"rate dated {published.published_on} is newer than the asked date {req.asked_date}"
            )
        if gap > self._settings.max_fallback_days:
            raise errors.no_rate_for_date(req.asked_date.isoformat(), published.published_on.isoformat())

        result = (req.amount * published.rate).quantize(_CENT, rounding=ROUND_HALF_UP)
        return Conversion(
            amount=req.amount,
            base=req.base,
            target=req.target,
            rate=published.rate,
            result=result,
            rate_date=published.published_on,
            asked_date=req.asked_date,
        )

    async def _published_rate(self, req: Request, today: date) -> PublishedRate:
        key = (req.base, req.target, req.asked_date)
        cached = self._cache.get(key)
        if cached is not None:
            rate, expires_at = cached
            if expires_at is None or expires_at > self._now():
                self._cache.move_to_end(key)
                return rate
            del self._cache[key]

        rate = await self._upstream.rate_on(req.base, req.target, req.asked_date)

        # A past day's answer is final. Today's may still change once the ECB
        # publishes this afternoon, so it is only trusted for a short while.
        expires_at = None if req.asked_date < today else self._now() + self._settings.today_cache_ttl_seconds
        self._cache[key] = (rate, expires_at)
        while len(self._cache) > self._settings.cache_max_entries:
            self._cache.popitem(last=False)
        return rate
