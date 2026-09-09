"""Short database readiness probe without cloud requests or credential disclosure."""

import psycopg

from signal_slate.config import get_settings
from signal_slate.db import normalize_psycopg_url


def database_available() -> bool:
    url = get_settings().database_url
    if not url:
        return False
    try:
        with psycopg.connect(
            normalize_psycopg_url(url),
            connect_timeout=2,
            options="-c statement_timeout=2000",
        ) as connection:
            connection.execute("SELECT 1")
        return True
    except Exception:
        return False
