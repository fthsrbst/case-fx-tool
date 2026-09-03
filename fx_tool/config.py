"""All configuration comes from environment variables; nothing else reads os.environ."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    upstream_base: str
    port: int
    upstream_timeout_seconds: float
    # A rate older than this many days is not offered as a fallback for the asked
    # date. Long weekends and holiday clusters fit comfortably inside a week; a
    # bigger gap means something is wrong upstream, not a holiday.
    max_fallback_days: int
    # How long a "today" answer is trusted before re-asking. The ECB publishes
    # around 16:00 CET, so a rate fetched at noon can be superseded the same day.
    today_cache_ttl_seconds: float
    cache_max_entries: int


def load_settings() -> Settings:
    return Settings(
        upstream_base=os.environ.get("FX_UPSTREAM_BASE", "https://api.frankfurter.dev").rstrip("/"),
        port=int(os.environ.get("PORT", "8080")),
        upstream_timeout_seconds=float(os.environ.get("FX_UPSTREAM_TIMEOUT", "5")),
        max_fallback_days=int(os.environ.get("FX_MAX_FALLBACK_DAYS", "7")),
        today_cache_ttl_seconds=float(os.environ.get("FX_TODAY_CACHE_TTL", "600")),
        cache_max_entries=int(os.environ.get("FX_CACHE_MAX_ENTRIES", "10000")),
    )
