# fx-tool

One HTTP endpoint an AI agent can call to convert money using European Central
Bank reference rates, fetched from [frankfurter.dev](https://frankfurter.dev).
The rule it is built around: **a wrong number is worse than no number.** It never
invents a rate, and it never labels a rate with a day it does not belong to.

## Run

```bash
./run.sh                      # http://localhost:8080
PORT=9000 ./run.sh            # another port
FX_UPSTREAM_BASE=http://localhost:9999 ./run.sh   # point at a fake upstream
```

Needs Python 3.11+. `run.sh` uses [uv](https://docs.astral.sh/uv/) if installed,
otherwise creates `.venv` with pip. The first dependency install needs network
access; tests themselves make no external requests (one checks localhost refusal).

```bash
curl 'localhost:8080/tools/convert?amount=250&from=EUR&to=TRY&date=2026-08-28'
```

## Test

```bash
./test.sh
```

The upstream is faked in-process (`tests/fake_upstream.py` mimics
the subset of Frankfurter behaviour used here). Rates are deterministic fixtures,
not a record of live prices. Part B evidence lives in `tests/test_review.py`.

## The endpoint

`GET /tools/convert?amount=250&from=EUR&to=TRY&date=2026-08-28`

| Parameter | Required | Notes |
|---|---|---|
| `amount` | yes | decimal, `1e-24` to `1e12`, at most 24 input characters; ten decimal places accepted |
| `from`, `to` | yes | ISO 4217 code, case-insensitive |
| `date` | no | `YYYY-MM-DD`; defaults to today in Frankfurt time (the ECB's calendar) |

Example success for a weekend query (`date=2026-08-29`), `200`:

```json
{
  "amount": 250, "from": "EUR", "to": "TRY",
  "rate": 56.1718, "result": 14042.95,
  "rate_date": "2026-08-28", "asked_date": "2026-08-29",
  "source": "ECB via frankfurter.dev",
  "rate_is_fallback": true,
  "note": "The provider returned an earlier rate for 2026-08-29; the rate used is from 2026-08-28."
}
```

- `rate` is passed through from the ECB unrounded. `result` is money: rounded to
  2 decimals, half up (a fixed tool policy, including JPY). Parsing, arithmetic
  and numeric JSON output use `Decimal` without a float conversion. Consumers
  need a decimal-aware JSON parser to preserve precision too.
- Accepted rates are finite, `1e-24` to `1e24`, with at most 36 significant
  digits and 96 characters in their parsed representation. These defensive
  limits keep arithmetic bounded; values outside them are `502 upstream_invalid`.
- `rate_date` is the day the ECB actually published the rate, as stated by the
  upstream itself. `asked_date` is what the caller asked for.
- `rate_is_fallback` is `true` whenever those two differ; `note` then spells it out
  so the model can tell the customer which day the number is from.

Failure, non-2xx: `{ "error": "<code>", "message": "<sentence>" }`.

## Error codes

| HTTP | `error` | When |
|---|---|---|
| 400 | `invalid_amount` | missing, not a number, zero, negative, NaN/inf, < 1e-24, > 1e12, > 24 characters |
| 400 | `invalid_currency` | missing, or not three letters |
| 400 | `same_currency` | `from` equals `to` |
| 400 | `invalid_date` | not `YYYY-MM-DD` or not a real calendar day |
| 400 | `date_in_future` | later than today (Frankfurt time) |
| 400 | `date_before_series` | before 1999-01-04, when euro reference rates begin |
| 404 | `unknown_currency` | upstream 404: unsupported pair or unavailable historical coverage (see NOTES) |
| 404 | `no_rate_for_date` | nearest earlier published rate is more than 7 days old |
| 502 | `upstream_error` | upstream answered 4xx/5xx other than 404 |
| 502 | `upstream_invalid` | not JSON, wrong shape, rate missing/non-numeric/non-positive/outside numeric limits, wrong base, or a rate dated *after* the asked day |
| 503 | `upstream_unavailable` | connection refused / DNS / TLS failure |
| 504 | `upstream_timeout` | HTTPX network operation timed out (default 5 s; `FX_UPSTREAM_TIMEOUT`) |

## What happens in each case the brief asks about

| Case | Behaviour |
|---|---|
| Weekend / holiday, no ECB rate that day | `200` with the most recent earlier rate. `rate_date` is that earlier day, `rate_is_fallback: true`, `note` explains. Frankfurter itself answers a weekend query with Friday's rate *dated Friday*; we read that date and pass it on. If the nearest rate is more than 7 days old: `404 no_rate_for_date`. |
| Date in the future | `400 date_in_future`, before touching the upstream. Frankfurter would happily answer tomorrow's query with today's rate; we do not let that through. |
| Date before the series | `400 date_before_series`, before touching the upstream. |
| Unknown currency code | `404 unknown_currency`. Malformed codes (`EURO`) are `400 invalid_currency` locally. |
| `from` == `to` | `400 same_currency`, no upstream call. |
| Upstream slow | `504 upstream_timeout`; timeout is per network operation, not a total request deadline. |
| Upstream 500 | `502 upstream_error`. |
| Upstream not JSON / wrong shape | `502 upstream_invalid`. |
| `amount` missing / zero / negative | `400 invalid_amount`. |
| `amount` with ten decimal places | accepted; echoed back as given; `result` rounded to cents. |
| Repeated question | answered from an in-memory cache keyed by `(from, to, date)`. Past responses have no TTL (historical stability assumption); today's answer is re-asked after 10 min (`FX_TODAY_CACHE_TTL`) because the ECB publishes around 16:00 CET. Failures are never cached. |

## Configuration

| Variable | Default | |
|---|---|---|
| `FX_UPSTREAM_BASE` | `https://api.frankfurter.dev` | `/v1/{date}` is appended |
| `PORT` | `8080` | |
| `FX_UPSTREAM_TIMEOUT` | `5` | seconds |
| `FX_MAX_FALLBACK_DAYS` | `7` | oldest rate offered as a stand-in |
| `FX_TODAY_CACHE_TTL` | `600` | seconds |
| `FX_CACHE_MAX_ENTRIES` | `10000` | LRU bound |

## Layout

```
fx_tool/config.py    env -> Settings, the only place os.environ is read
fx_tool/upstream.py  the only HTTP client; validates what frankfurter.dev sends
fx_tool/service.py   input parsing, date policy, cache, Decimal arithmetic
fx_tool/app.py       FastAPI wiring and the error shape
tests/               offline tests + fake upstream
tool.py, REVIEW.md   Part B: the file under review and the review
NOTES.md             decisions, next steps, AI tooling
```
