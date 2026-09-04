import json
from decimal import Decimal

import httpx
import pytest


PARAMS = {"amount": "1", "from": "EUR", "to": "TRY", "date": "2026-08-28"}


@pytest.mark.parametrize("published,status", [("2026-09-03", 502), ("2026-08-01", 404)])
def test_rejected_rate_does_not_prevent_recovery(client, upstream, published, status):
    upstream.fail_with = httpx.Response(
        200, json={"base": "EUR", "date": published, "rates": {"TRY": 56}}
    )
    assert client.get("/tools/convert", params=PARAMS).status_code == status
    upstream.fail_with = None
    recovered = client.get("/tools/convert", params=PARAMS)
    assert recovered.status_code == 200
    assert recovered.json()["rate"] == 56.1718
    assert len(upstream.calls) == 2


def test_json_rate_keeps_precision_before_rounding(client, upstream):
    upstream.fail_with = httpx.Response(
        200, content='{"base":"EUR","date":"2026-08-28","rates":{"TRY":1.00499999999999999}}'
    )
    response = client.get("/tools/convert", params=PARAMS)
    assert response.status_code == 200
    body = json.loads(response.text, parse_float=Decimal)
    assert body["rate"] == Decimal("1.00499999999999999")
    assert body["result"] == Decimal("1.00")


@pytest.mark.parametrize("amount", ["999999999999.1234567890", "0.0000000000000000000001"])
def test_numeric_json_preserves_amount(client, amount):
    response = client.get("/tools/convert", params={**PARAMS, "amount": amount})
    assert response.status_code == 200
    body = json.loads(response.text, parse_float=Decimal)
    assert body["amount"] == Decimal(amount)
    expected = (Decimal(amount) * Decimal("56.1718")).quantize(Decimal("0.01"))
    assert body["result"] == expected


@pytest.mark.parametrize("rate", ["1e100", "1e-1000000", "NaN", "Infinity"])
def test_unusable_rate_returns_error_and_can_recover(client, upstream, rate):
    upstream.fail_with = httpx.Response(
        200, json={"base": "EUR", "date": "2026-08-28", "rates": {"TRY": rate}}
    )
    response = client.get("/tools/convert", params=PARAMS)
    assert response.status_code == 502
    assert response.json()["error"] == "upstream_invalid"
    upstream.fail_with = None
    assert client.get("/tools/convert", params=PARAMS).status_code == 200
    assert len(upstream.calls) == 2


def test_extreme_amount_exponent_is_rejected_locally(client, upstream):
    response = client.get("/tools/convert", params={**PARAMS, "amount": "1e-1000000"})
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_amount"
    assert not upstream.calls
