# Review of tool.py

Ranked by customer impact. Verification is reproducible without live rates:
`./test.sh tests/test_review.py`. These tests assert the defects in the original
`tool.py`, which is intentionally unchanged; green means the finding reproduces.

## 1. Wrong dates make plausible rates misleading — fix first

`fetch_rate` ignores the upstream date and labels the rate with the requested
day. Its cache key contains only the currency pair: asking for another date
reuses the first rate. A historical conversion can therefore use today's rate,
and a future date can appear to have a published rate. Missing rates also trigger
an unrestricted fallback to `/latest`, even for dates before the series began.

**Verify:** stub August 28 at 60 and August 21 at 50; ask for August 28, then
August 21. Both return 60, with different date labels. The concurrent test holds
the old-day response until the new-day response completes: the old response
then overwrites the shared cache, and the next new-day query returns 50.

**Before shipping:** reject future/pre-series dates; return the upstream date;
permit only an explicitly labelled, bounded earlier-date fallback; key the cache
by pair and resolved requested day, with a TTL for today. Validate before caching.
This is my first fix because the answer can look credible while describing the
wrong day. A lock alone cannot repair the missing date in the key.

## 2. Caught failures become successful zero-value conversions

`except Exception` returns HTTP 200 with zero rate/result. An upstream outage,
invalid JSON or unsupported pair can tell the customer their money is worthless.
The response gives the agent no error code to handle.

**Verify:** inject HTTP 500 with a text body or `ReadTimeout`; both produce a
200 with zero values. **Fix:** check upstream status and translate known failures
into non-2xx `{error, message}` responses. Do not manufacture a rate.

## 3. Rounding the rate materially changes the result

`round(rate, 2)` runs before multiplication. With a fixed TRY/EUR rate of
0.0178, 1000 TRY becomes 20.00 EUR instead of 17.80 EUR, about 12.36% too high.
Rates below 0.005 can become zero.

**Verify:** the rounding test injects exactly 0.0178. **Fix:** preserve the rate,
calculate with Decimal, and round only the final result under a stated policy.

## 4. The brief's query parameters are silently ignored

FastAPI exposes `from_` and `on`, while the caller sends `from` and `date`.
A USD historical request can become a EUR latest conversion; `asked_date` is
also absent.

**Verify:** send `from=USD&date=2026-08-21`; the test receives EUR and the latest
stub rate. **Fix:** alias `from`, expose `date`, and return both date fields.

## Suspicious details worth distinguishing

- HTTPX has a default five-second timeout per network operation, not a total
  request deadline. The principal defect is swallowing timeout errors.
- FastAPI already rejects missing/non-numeric amounts with 422 (tested).
  Positive/finite amount and date business rules still need validation.
- Hardcoding the host prevents environment-based substitution, but does not
  prevent offline testing: the tests replace the HTTP client transport.
