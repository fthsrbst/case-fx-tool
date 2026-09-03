# Review of tool.py

Reviewed as if it ships tomorrow to a paying customer, behind a language model
that repeats whatever number it gets. Every finding below was reproduced by
running `uvicorn tool:app` against the live upstream on 2026-09-03; the commands
are the verification.

## 1. It labels rates with days they do not belong to, and the label gets worse the longer it runs

`rate_date` is never read from the upstream. It is `str(on or date.today())`:
whatever the caller asked for, echoed back. On top of that the cache key is
`"EUR-TRY"` with no date and no expiry, so the first rate fetched for a pair is
served for **every** date, forever, each time stamped with the date that was asked.

What the customer gets: "the rate on 2026-08-21 was 56.12" (that was today's
rate; the real one was different). "On 2027-06-01 it is 56.12." "On 1998-01-01,
100 EUR was 116 USD" (the euro did not exist; the 404 fallback silently swapped in
today's rate). And from tomorrow on, every "latest" answer is today's rate with
tomorrow's date on it, until someone restarts the process. These numbers look
plausible; nobody can tell they are wrong from the response.

Verify:

```
GET /tools/convert?amount=100&from_=EUR&to=USD&on=1998-01-01   -> 200, rate_date "1998-01-01", today's rate
GET ...?on=2026-09-03  then  GET ...?on=2026-08-21           -> identical rate, different rate_date
GET ...?on=2027-06-01                                        -> 200, a rate for a date in the future
```

## 2. Every failure is a 200 with `rate: 0.0, result: 0.0`

The `except Exception` in `convert` turns unknown currency, `from == to`,
upstream 5xx, non-JSON bodies, timeouts and the `KeyError` from the 404 fallback
into a success response saying the money is worth nothing. The model has no
`error` field to react to, so the customer hears "250 EUR is 0 TRY" or, worse,
"your 100 IDR are worth 0 EUR" (see 3).

Verify:

```
GET ...?amount=250&from_=EUR&to=XXX   -> 200 {"rate":0.0,"result":0.0}
GET ...?amount=250&from_=EUR&to=EUR   -> 200 {"rate":0.0,"result":0.0}
FX upstream down (block DNS)          -> 200 {"rate":0.0,"result":0.0}
```

## 3. The rate is rounded to two decimals before multiplying

`rate = round(rate, 2)`. For EUR→TRY that hides a few tenths of a percent. For
any pair where the rate is small it is a large error: TRY→EUR is 0.0178 and
becomes 0.02, a 12 % overstatement, so 1000 TRY is reported as 20.00 EUR instead
of 17.80. IDR→EUR (0.0000488) becomes 0.0: a customer with money is told they
have none, with HTTP 200.

Verify:

```
GET ...?amount=1000&from_=TRY&to=EUR  -> rate 0.02, result 20.0   (real: 0.0178, 17.82)
GET ...?amount=100&from_=IDR&to=EUR   -> rate 0.0,  result 0.0
```

## 4. The `from` parameter is silently ignored

The query parameter is `from_` (no alias), and the brief's `from` is discarded
by FastAPI. `?from=USD&to=TRY` converts EUR to TRY. The response does echo
`"from": "EUR"`, so an attentive model could notice, but a model that already
believes it sent USD will read the number as USD→TRY, roughly 15 % too high.
Same class: the date parameter is `on`, not `date`, and `asked_date` is missing.

Verify: `GET ...?amount=100&from=USD&to=TRY` → `"from": "EUR"`, EUR rate.

## 5. No input validation

Negative and zero amounts, `1e308`, future dates and `from == to` all pass
through. Negative amounts produce negative results with 200. Not as harmful as
1–3 because the caller sent nonsense, but a tool for a language model should
refuse nonsense loudly rather than compute with it.

Verify: `GET ...?amount=-250&from_=EUR&to=TRY` → `"result": -14030.0`.

## Lesser

- `UPSTREAM` is hardcoded, so it cannot be tested without the internet or pointed
  at a fake; no `raise_for_status`; errors go to `print`; the `AsyncClient` is
  never closed. None of these hurt a customer directly; they hurt whoever has to
  find out why a customer was hurt.

## The one I would fix before shipping tonight

**Finding 1.** Three small changes in `fetch_rate`: key the cache by
`(base, target, date)`, take `rate_date` from `payload["date"]` and refuse a
result whose date is after the asked one, and reject future dates before calling
out. It is the only defect that produces *plausible* wrong numbers with no way to
detect them from the response, and it gets worse every hour the process lives.
Finding 2 is a three-line change I would put in the same commit if allowed, and
if I were only allowed one line it would be `raise` instead of `return` in that
`except`.

## Things that look suspicious but are fine

- **"There is no timeout on the upstream call."** There is: `httpx.AsyncClient()`
  defaults to 5 seconds on connect, read, write and pool. A slow upstream ends in
  a `TimeoutException`, which finding 2 then turns into `0.0`, but the hang itself
  does not happen.
- **Falling back to the latest published rate on weekends and holidays** is the
  right idea; my own service does the same. The problem is only the execution:
  the branch never fires for a real weekend (the upstream already returns Friday's
  rate for a Saturday query), it fires for 404s where it should not (unknown
  currency, dates before 1999), and the date is not passed on.
- **`round(amount * rate, 2)` on the result** is fine for money; the defect is
  rounding the *rate* first. (Float arithmetic here is half-to-even, so
  `round(0.125, 2)` is `0.12`; that is a cent, and a separate, minor
  conversation.)
- **`from __future__ import annotations` with FastAPI signatures** works on
  Python 3.10+; the `date | None` parameter is parsed correctly.
- **The module-level `_cache` dict is not locked.** Single event loop, no await
  between read and write of the same key; a race here only causes a duplicate
  fetch, never a wrong value.
