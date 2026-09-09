"""Database connection verification test.

Only runs when explicit database check is requested or DATABASE_URL is available.
Offline tests in tests/unit do not require database.
"""

import pytest
from signal_slate.config import get_settings
from signal_slate.db import check_database_connection


def test_database_connection_if_configured():
    settings = get_settings()
    if not settings.database_url:
        pytest.skip("DATABASE_URL is not configured; skipping explicit DB check")

    res = check_database_connection()
    assert res["status"] == "ok", f"DB check failed: {res.get('message')}"
    assert "PostgreSQL" in res["version"]
    assert res["database"] == "signal_slate"
