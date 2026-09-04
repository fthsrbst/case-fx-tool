# Notes

## Decisions

**Earlier rates are visible.** Weekend/holiday queries may use an earlier rate,
with the upstream's actual `rate_date`, the requested `asked_date`, a fallback
flag and a note. Gaps over seven days are refused. Future and pre-series dates
are rejected locally; today's date follows Europe/Berlin. An ECB reference
conversion is an estimate, not proof of the rate a bank charged a customer.

**One rounding step.** JSON rates are parsed directly into Decimal; a local
64-digit context keeps multiplication exact within the documented input bounds.
Only the result is rounded, half up to two decimals (a tool policy, not a
currency-specific settlement rule). `simplejson` writes Decimal as JSON numbers
without float conversion. Clients must also use a decimal-aware parser to retain
that precision. Extreme numbers are rejected, not silently rounded or overflowed.

**Cache only validated rates.** The bounded in-memory cache uses `(from, to,
requested day)`. Historical responses have no TTL; today's expire after ten
minutes. This assumes historical publication data is stable. Failures, including
invalid/stale rate dates, are never cached. Different amounts reuse the same rate.

**404 is ambiguous.** After local date checks, upstream 404 maps to
`unknown_currency`; a supported currency with no historical coverage can receive
that code too. The message acknowledges this limitation rather than claiming
the code never exists.

## With another day

- Coalesce simultaneous cache misses for the same key into one upstream fetch.
- Use currency metadata to distinguish unsupported codes from historical gaps.
- Add request latency/cache-hit logging and a refresh policy for historical corrections.

## AI tools

Claude Code was used for the initial API exploration, implementation, tests and
review draft. Codex then reviewed the submission and reproduced defects using
controlled upstream responses, added regression tests, corrected Decimal handling
and cache validation, and shortened the review. Part B's executable evidence
is in `tests/test_review.py`; the supplied `tool.py` remains unchanged.

## One thing the AI got wrong

The initial review claimed the cache had no await between reading and writing,
so a race could only duplicate a fetch. Codex's controlled concurrency test held
an old-date response until a newer-date request finished: the late response
overwrote the shared pair-only key. That disproved the claim. The corrected
review identifies the missing date in the key; a lock alone would not fix it.
The implementation also cached rates before validating their dates. Recovery
tests failed until those checks were moved before insertion.
