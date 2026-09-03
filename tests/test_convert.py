"""Behaviour of GET /tools/convert against a faked upstream. No network is used."""

from __future__ import annotations

import socket
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from fx_tool.app import create_app
from tests.conftest import TODAY, make_settings
from tests.fake_upstream import FakeFrankfurter


def convert(client, **params):
    return client.get("/tools/convert", params=params)


# --- the happy path and the date policy ---------------------------------------


def test_exact_published_day(client, upstream):
    r = convert(client, amount=250, **{"from": "EUR"}, to="TRY", date="2026-08-28")
    assert r.status_code == 200
    assert r.json() == {
        "amount": 250,
        "from": "EUR",
        "to": "TRY",
        "rate": 56.1718,
        "result": 14042.95,
        "rate_date": "2026-08-28",
        "asked_date": "2026-08-28",
        "source": "ECB via frankfurter.dev",
        "rate_is_fallback": False,
    }
    assert len(upstream.calls) == 1
    assert upstream.calls[0].url.path == "/v1/2026-08-28"


def test_weekend_returns_fridays_rate_and_says_so(client):
    r = convert(client, amount=100, **{"from": "EUR"}, to="TRY", date="2026-08-29")
    assert r.status_code == 200
    body = r.json()
    assert body["rate_date"] == "2026-08-28"
    assert body["asked_date"] == "2026-08-29"
    assert body["rate_is_fallback"] is True
    assert "2026-08-28" in body["note"]
    assert body["rate"] == 56.1718


def test_gap_longer_than_policy_is_refused(client):
    # Nearest earlier published day is 2026-08-21, eight days before.
    r = convert(client, amount=1, **{"from": "EUR"}, to="TRY", date="2026-08-29")
    assert r.status_code == 200  # one day gap: fine

    settings = make_settings(max_fallback_days=3)
    fake = FakeFrankfurter()
    with TestClient(create_app(settings, transport=fake.transport(), clock=lambda: TODAY)) as c:
        r = convert(c, amount=1, **{"from": "EUR"}, to="TRY", date="2026-08-26")
    assert r.status_code == 404
    assert r.json()["error"] == "no_rate_for_date"
    assert "2026-08-21" in r.json()["message"]


def test_future_date_is_refused_without_asking_upstream(client, upstream):
    r = convert(client, amount=1, **{"from": "EUR"}, to="TRY", date="2026-09-04")
    assert r.status_code == 400
    assert r.json()["error"] == "date_in_future"
    assert upstream.calls == []


def test_date_before_series_is_refused_without_asking_upstream(client, upstream):
    r = convert(client, amount=1, **{"from": "EUR"}, to="USD", date="1999-01-01")
    assert r.status_code == 400
    assert r.json()["error"] == "date_before_series"
    assert upstream.calls == []


def test_missing_date_means_today(client, upstream):
    r = convert(client, amount=1, **{"from": "EUR"}, to="TRY")
    assert r.status_code == 200
    assert r.json()["asked_date"] == "2026-09-03"
    assert upstream.calls[0].url.path == "/v1/2026-09-03"


def test_upstream_rate_newer_than_asked_is_never_presented(client, upstream):
    upstream.fail_with = httpx.Response(
        200, json={"amount": 1.0, "base": "EUR", "date": "2026-09-03", "rates": {"TRY": 56.1177}}
    )
    r = convert(client, amount=1, **{"from": "EUR"}, to="TRY", date="2026-08-28")
    assert r.status_code == 502
    assert r.json()["error"] == "upstream_invalid"


# --- currencies -----------------------------------------------------------------


def test_unknown_currency(client):
    r = convert(client, amount=1, **{"from": "EUR"}, to="XXX", date="2026-08-28")
    assert r.status_code == 404
    assert r.json()["error"] == "unknown_currency"


def test_malformed_currency_code(client, upstream):
    r = convert(client, amount=1, **{"from": "EURO"}, to="TRY")
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_currency"
    assert upstream.calls == []


def test_same_currency(client, upstream):
    r = convert(client, amount=1, **{"from": "eur"}, to="EUR")
    assert r.status_code == 400
    assert r.json()["error"] == "same_currency"
    assert upstream.calls == []


def test_lowercase_codes_are_normalised(client):
    r = convert(client, amount=1, **{"from": "eur"}, to="try", date="2026-08-28")
    assert r.status_code == 200
    assert (r.json()["from"], r.json()["to"]) == ("EUR", "TRY")


def test_non_euro_pair_uses_cross_rate(client):
    r = convert(client, amount=100, **{"from": "USD"}, to="TRY", date="2026-08-28")
    assert r.status_code == 200
    assert r.json()["rate"] == pytest.approx(56.1718 / 1.1672)


# --- amount ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "amount",
    [None, "", "0", "-5", "abc", "NaN", "Infinity", "1e13", "1" * 30],
)
def test_bad_amounts_are_rejected_without_asking_upstream(client, upstream, amount):
    params = {"from": "EUR", "to": "TRY", "date": "2026-08-28"}
    if amount is not None:
        params["amount"] = amount
    r = client.get("/tools/convert", params=params)
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_amount"
    assert upstream.calls == []


def test_ten_decimal_places_are_accepted_and_result_is_money(client):
    r = convert(client, amount="1.0000000001", **{"from": "EUR"}, to="TRY", date="2026-08-28")
    assert r.status_code == 200
    assert r.json()["amount"] == 1.0000000001
    assert r.json()["result"] == 56.17


def test_result_rounds_half_up_and_rate_is_not_rounded(client, upstream):
    upstream.fail_with = httpx.Response(
        200, json={"amount": 1.0, "base": "TRY", "date": "2026-08-28", "rates": {"EUR": 0.0178}}
    )
    r = convert(client, amount=7, **{"from": "TRY"}, to="EUR", date="2026-08-28")
    body = r.json()
    assert body["rate"] == 0.0178  # tool.py would have rounded this to 0.02
    assert body["result"] == 0.12  # 0.1246 -> 0.12
    upstream.fail_with = httpx.Response(
        200, json={"amount": 1.0, "base": "TRY", "date": "2026-08-27", "rates": {"EUR": 0.125}}
    )
    r = convert(client, amount=1, **{"from": "TRY"}, to="EUR", date="2026-08-27")
    assert r.json()["result"] == 0.13  # half up, not banker's 0.12


# --- upstream failures ----------------------------------------------------------


def test_upstream_500(client, upstream):
    upstream.fail_with = httpx.Response(500, text="boom")
    r = convert(client, amount=1, **{"from": "EUR"}, to="TRY", date="2026-08-28")
    assert r.status_code == 502
    assert r.json()["error"] == "upstream_error"


def test_upstream_not_json(client, upstream):
    upstream.fail_with = httpx.Response(200, text="<html>maintenance</html>")
    r = convert(client, amount=1, **{"from": "EUR"}, to="TRY", date="2026-08-28")
    assert r.status_code == 502
    assert r.json()["error"] == "upstream_invalid"


def test_upstream_json_without_rate(client, upstream):
    upstream.fail_with = httpx.Response(200, json={"base": "EUR", "date": "2026-08-28", "rates": {}})
    r = convert(client, amount=1, **{"from": "EUR"}, to="TRY", date="2026-08-28")
    assert r.status_code == 502
    assert r.json()["error"] == "upstream_invalid"


def test_upstream_timeout(client, upstream):
    upstream.fail_with = httpx.ReadTimeout("slow")
    r = convert(client, amount=1, **{"from": "EUR"}, to="TRY", date="2026-08-28")
    assert r.status_code == 504
    assert r.json()["error"] == "upstream_timeout"


def test_upstream_closed_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    settings = make_settings(upstream_base=f"http://127.0.0.1:{port}")
    with TestClient(create_app(settings, clock=lambda: TODAY)) as c:
        r = convert(c, amount=1, **{"from": "EUR"}, to="TRY", date="2026-08-28")
    assert r.status_code == 503
    assert r.json()["error"] == "upstream_unavailable"


def test_failure_is_never_cached(client, upstream):
    upstream.fail_with = httpx.Response(500)
    convert(client, amount=1, **{"from": "EUR"}, to="TRY", date="2026-08-28")
    upstream.fail_with = None
    r = convert(client, amount=1, **{"from": "EUR"}, to="TRY", date="2026-08-28")
    assert r.status_code == 200
    assert len(upstream.calls) == 2


# --- cache ----------------------------------------------------------------------


def test_repeat_question_does_not_ask_upstream_again(client, upstream):
    for _ in range(3):
        r = convert(client, amount=250, **{"from": "EUR"}, to="TRY", date="2026-08-28")
        assert r.status_code == 200
    assert len(upstream.calls) == 1
    # A different amount is the same rate question.
    convert(client, amount=99, **{"from": "EUR"}, to="TRY", date="2026-08-28")
    assert len(upstream.calls) == 1


def test_cache_is_keyed_by_date_and_pair(client, upstream):
    convert(client, amount=1, **{"from": "EUR"}, to="TRY", date="2026-08-28")
    convert(client, amount=1, **{"from": "EUR"}, to="TRY", date="2026-08-27")
    convert(client, amount=1, **{"from": "EUR"}, to="USD", date="2026-08-28")
    convert(client, amount=1, **{"from": "TRY"}, to="EUR", date="2026-08-28")
    assert len(upstream.calls) == 4
    r = convert(client, amount=1, **{"from": "EUR"}, to="TRY", date="2026-08-27")
    assert r.json()["rate"] == 56.1
    assert len(upstream.calls) == 4


def test_todays_answer_is_re_asked_after_ttl(upstream):
    clock = {"now": 1000.0}
    settings = make_settings(today_cache_ttl_seconds=60)
    app = create_app(settings, transport=upstream.transport(), clock=lambda: TODAY)
    with TestClient(app) as c:
        c.app.state.converter._now = lambda: clock["now"]
        convert(c, amount=1, **{"from": "EUR"}, to="TRY")
        clock["now"] += 30
        convert(c, amount=1, **{"from": "EUR"}, to="TRY")
        assert len(upstream.calls) == 1
        clock["now"] += 31
        convert(c, amount=1, **{"from": "EUR"}, to="TRY")
        assert len(upstream.calls) == 2
        # Yesterday is final: never re-asked.
        convert(c, amount=1, **{"from": "EUR"}, to="TRY", date="2026-09-02")
        clock["now"] += 10_000
        convert(c, amount=1, **{"from": "EUR"}, to="TRY", date="2026-09-02")
        assert len(upstream.calls) == 3
