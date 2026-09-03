from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from fx_tool.app import create_app
from fx_tool.config import Settings
from tests.fake_upstream import FakeFrankfurter

TODAY = date(2026, 9, 3)  # a Thursday, with a rate published


def make_settings(**overrides) -> Settings:
    base = dict(
        upstream_base="http://fake-upstream.test",
        port=0,
        upstream_timeout_seconds=1.0,
        max_fallback_days=7,
        today_cache_ttl_seconds=600,
        cache_max_entries=100,
    )
    base.update(overrides)
    return Settings(**base)


@pytest.fixture
def upstream() -> FakeFrankfurter:
    return FakeFrankfurter()


@pytest.fixture
def client(upstream: FakeFrankfurter):
    app = create_app(make_settings(), transport=upstream.transport(), clock=lambda: TODAY)
    with TestClient(app) as c:
        yield c
