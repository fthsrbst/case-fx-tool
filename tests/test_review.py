"""Executable evidence for REVIEW.md; the supplied tool.py stays unchanged."""

import asyncio
from datetime import date

import httpx
import pytest
from fastapi.testclient import TestClient

import tool


@pytest.fixture
def reviewed_client(monkeypatch):
    def handle(request):
        day = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, json={
            "date": "2026-08-28" if day == "latest" else day,
            "rates": {"TRY": 50 if day == "2026-08-21" else 60, "EUR": 0.0178},
        })

    upstream = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    monkeypatch.setattr(tool, "client", upstream)
    monkeypatch.setattr(tool, "_cache", {})
    with TestClient(tool.app) as client:
        yield client
    asyncio.run(upstream.aclose())


def test_review_different_dates_share_a_rate(reviewed_client):
    params = {"amount": 1, "from_": "EUR", "to": "TRY"}
    first = reviewed_client.get("/tools/convert", params={**params, "on": "2026-08-28"}).json()
    second = reviewed_client.get("/tools/convert", params={**params, "on": "2026-08-21"}).json()
    assert first["rate"] == second["rate"] == 60
    assert second["rate_date"] == "2026-08-21"  # Stub rate for this day is 50.


def test_review_concurrent_old_response_overwrites_new_date(monkeypatch):
    async def run():
        started, release = asyncio.Event(), asyncio.Event()

        async def handle(request):
            day = request.url.path.rsplit("/", 1)[-1]
            if day == "2026-08-21":
                started.set()
                await release.wait()
            return httpx.Response(200, json={
                "date": day, "rates": {"TRY": 50 if day == "2026-08-21" else 60},
            })

        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as upstream:
            monkeypatch.setattr(tool, "client", upstream)
            monkeypatch.setattr(tool, "_cache", {})
            old = asyncio.create_task(tool.fetch_rate("EUR", "TRY", date(2026, 8, 21)))
            try:
                await asyncio.wait_for(started.wait(), timeout=2)
                assert await tool.fetch_rate("EUR", "TRY", date(2026, 8, 28)) == (60, "2026-08-28")
            finally:
                release.set()
                await old
            assert await tool.fetch_rate("EUR", "TRY", date(2026, 8, 28)) == (50, "2026-08-28")

    asyncio.run(run())


@pytest.mark.parametrize("failure", [httpx.Response(500, text="failure"), httpx.ReadTimeout("slow")])
def test_review_upstream_failures_become_zero_success(reviewed_client, monkeypatch, failure):
    async def fail(*args, **kwargs):
        if isinstance(failure, Exception):
            raise failure
        return failure

    monkeypatch.setattr(tool.client, "get", fail)
    response = reviewed_client.get("/tools/convert", params={"amount": 250})
    assert response.status_code == 200
    assert response.json()["result"] == response.json()["rate"] == 0
    assert "error" not in response.json()


def test_review_rate_rounding_changes_customer_amount(reviewed_client):
    response = reviewed_client.get("/tools/convert", params={"amount": 1000, "from_": "TRY", "to": "EUR"})
    assert response.json()["rate"] == 0.02
    assert response.json()["result"] == 20  # Exact stub rate would give 17.80.


def test_review_brief_parameter_names_are_ignored(reviewed_client):
    response = reviewed_client.get("/tools/convert", params={
        "amount": 1, "from": "USD", "to": "TRY", "date": "2026-08-21",
    })
    assert response.json()["from"] == "EUR"
    assert response.json()["rate"] == 60  # Requested historical rate was 50.
    assert "asked_date" not in response.json()


@pytest.mark.parametrize("params", [{}, {"amount": "abc"}])
def test_review_fastapi_does_validate_types(reviewed_client, params):
    assert reviewed_client.get("/tools/convert", params=params).status_code == 422
