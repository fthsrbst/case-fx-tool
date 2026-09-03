"""An in-process stand-in for frankfurter.dev with the same observable behaviour.

Real facts it mimics (checked against the live API on 2026-09-03):
- /v1/{date} answers with the newest published day at or before {date} and
  states that day in "date" (weekends get Friday's rate, dated Friday).
- unknown currency -> 404 {"message": "not found"}
- from == to     -> 422 {"message": "bad currency pair"}
"""

from __future__ import annotations

import json
from datetime import date

import httpx

# Published days only; 2026-08-29/30 is a weekend, 2026-08-24..26 are missing on purpose.
RATES: dict[date, dict[str, float]] = {
    date(2026, 8, 20): {"TRY": 55.9000, "USD": 1.1600, "JPY": 171.20},
    date(2026, 8, 21): {"TRY": 56.0000, "USD": 1.1610, "JPY": 171.40},
    date(2026, 8, 27): {"TRY": 56.1000, "USD": 1.1650, "JPY": 171.80},
    date(2026, 8, 28): {"TRY": 56.1718, "USD": 1.1672, "JPY": 172.03},
    date(2026, 8, 31): {"TRY": 56.1500, "USD": 1.1680, "JPY": 172.10},
    date(2026, 9, 1): {"TRY": 56.1300, "USD": 1.1690, "JPY": 172.30},
    date(2026, 9, 2): {"TRY": 56.1200, "USD": 1.1700, "JPY": 172.50},
    date(2026, 9, 3): {"TRY": 56.1177, "USD": 1.1705, "JPY": 172.60},
}
KNOWN = {"EUR", *RATES[date(2026, 9, 3)].keys()}


class FakeFrankfurter:
    def __init__(self) -> None:
        self.calls: list[httpx.Request] = []
        # Set one of these to force a failure on the next call(s).
        self.fail_with: httpx.Response | Exception | None = None
        self.rates = {d: dict(r) for d, r in RATES.items()}

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if isinstance(self.fail_with, Exception):
            raise self.fail_with
        if self.fail_with is not None:
            return self.fail_with

        base = request.url.params.get("base", "EUR").upper()
        symbols = request.url.params.get("symbols", "").upper()
        asked = date.fromisoformat(request.url.path.rsplit("/", 1)[-1])

        if base not in KNOWN or symbols not in KNOWN:
            return _json(404, {"message": "not found"})
        if base == symbols:
            return _json(422, {"message": "bad currency pair"})

        published = max((d for d in self.rates if d <= asked), default=None)
        if published is None:
            return _json(404, {"message": "not found"})
        eur_rates = {"EUR": 1.0, **self.rates[published]}
        rate = eur_rates[symbols] / eur_rates[base]
        return _json(200, {"amount": 1.0, "base": base, "date": published.isoformat(), "rates": {symbols: rate}})


def _json(status: int, body: dict) -> httpx.Response:
    return httpx.Response(status, content=json.dumps(body).encode(), headers={"content-type": "application/json"})
