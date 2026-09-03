# Notes

## Decisions

**A missing rate is answered with the nearest earlier one, and the response says so.**
Frankfurter itself answers a Saturday query with Friday's rate *dated Friday*. I
read that date and pass it on as `rate_date`, set `rate_is_fallback: true` and add
a one-sentence `note`, so the model can tell the customer "this is Friday's rate".
The alternative, refusing weekends outright, makes the tool useless two days a
week for a question ("what did I pay on Saturday?") that has a well-understood
answer. Two guard rails: a rate older than 7 days is refused (`no_rate_for_date`),
and a rate dated *after* the asked day is refused as `upstream_invalid`, because
nothing legitimate produces it.

**Future dates are refused before touching the upstream.** Live probe: Frankfurter
answers tomorrow's date with today's rate, HTTP 200. Trusting that would present a
rate as belonging to a day that has no rate yet. "Today" is the ECB's day
(Europe/Berlin), not the server's.

**Amounts are `Decimal` end to end.** Ten decimal places are accepted and echoed
back; `result` is quantised to cents, half up; the rate is passed through
unrounded. Money never goes through a float except at JSON serialisation.

**Cache keyed by `(from, to, date)`.** Past days are final and cached for good;
"today" is cached for 10 minutes because the ECB publishes around 16:00 CET and a
noon answer is superseded the same afternoon. Failures are never cached.

**`unknown_currency` is inferred from an upstream 404** once local checks have
ruled out future and pre-1999 dates. Calling `/v1/currencies` first would be
more exact but adds a second endpoint the fake upstream must serve.

## With another day

- Deduplicate concurrent identical requests (one in-flight fetch per key); today
  two simultaneous first questions both hit the upstream.
- Warm the cache with `/v1/currencies` once at start, with a TTL, for a precise
  `unknown_currency` versus `no_rate_for_date` distinction.
- Structured logging with the upstream latency and cache hit/miss per request, and
  a tiny `/health` that reports upstream reachability.
- Property tests for the arithmetic (result never exceeds `amount * rate`
  rounded, inverse pairs agree within a cent).
- A `tool.py` pull request applying REVIEW.md findings 1 and 2.

## AI tools

Claude Code, throughout. I gave it the brief and the two questions I needed to
decide myself (holiday policy, amount precision); it probed the live API for the
edge cases, drafted the modules and the test suite, and I read every file before
it was committed. Part B was done the same way: it listed the suspicions, then
each one was reproduced against a running `tool.py` before it went into
REVIEW.md, and the "not a timeout problem" finding came from that check rather
than from reading.

## One thing the AI got wrong

Small and concrete: while silencing test warnings it appended
`filterwarnings` to the end of `pyproject.toml`, which landed it inside the
`[tool.hatch]` table instead of `[tool.pytest.ini_options]`. The test run still
printed the warnings; that is how it was noticed, and the line was moved. The
more useful catch was one it nearly did not make: its first probe of the upstream
used a far-future date, got a 404, and would have concluded "future dates fail
upstream, nothing to do". Probing *tomorrow* showed a 200 with today's rate. The
lesson I took: check the boundary right next to the edge, not far from it.
