"""Validate container settings, migrate the external database, then start the app."""

import os
import sys
import time
from urllib.parse import urlsplit

from alembic import command
from alembic.config import Config

from signal_slate.config import get_settings
from signal_slate.db import normalize_psycopg_url
from signal_slate.readiness_health import database_available


def validate_environment() -> None:
    database_url = get_settings().database_url
    if not database_url:
        raise ValueError("Set DATABASE_URL to the existing PostgreSQL database connection URL.")
    try:
        normalize_psycopg_url(database_url)
    except Exception:
        raise ValueError("DATABASE_URL must be a valid PostgreSQL connection URL.") from None
    origins = os.getenv("SIGNAL_SLATE_ALLOWED_ORIGINS", "").split(",")
    secure = os.getenv("SIGNAL_SLATE_SECURE_COOKIES", "true")
    if secure not in {"true", "false"}:
        raise ValueError("SIGNAL_SLATE_SECURE_COOKIES must be true or false.")
    for origin in origins:
        value = origin.strip()
        try:
            parsed = urlsplit(value)
            valid = (
                parsed.scheme in {"http", "https"}
                and parsed.hostname
                and not parsed.username
                and not parsed.password
                and not parsed.path
                and not parsed.query
                and not parsed.fragment
                and "*" not in value
            )
            _ = parsed.port
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("Set SIGNAL_SLATE_ALLOWED_ORIGINS to exact origins without paths.")
        if secure == "true" and parsed.scheme != "https":
            raise ValueError("HTTPS is required while SIGNAL_SLATE_SECURE_COOKIES=true.")


def main() -> int:
    try:
        validate_environment()
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    for attempt in range(12):
        if database_available():
            break
        if attempt == 11:
            print(
                "PostgreSQL is unavailable. Check its URL, TLS and network access.", file=sys.stderr
            )
            return 1
        time.sleep(2)
    try:
        command.upgrade(Config("alembic.ini"), "head")
    except Exception:
        print(
            "Database migration failed. Check database access and schema permissions.",
            file=sys.stderr,
        )
        return 1
    os.execvp(
        "uvicorn",
        [
            "uvicorn",
            "signal_slate.main:app",
            "--host",
            "0.0.0.0",
            "--port",
            "8000",
            "--workers",
            "1",
            "--no-proxy-headers",
        ],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
