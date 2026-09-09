"""Database setup and connection verification for Signal Slate.

Strictly uses PostgreSQL 17+ via psycopg/SQLAlchemy.
NO silent SQLite fallback is permitted.
"""

from typing import Any

import psycopg
from sqlalchemy import create_engine
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import declarative_base, sessionmaker

from signal_slate.config import get_settings

Base = declarative_base()

# Supported schemes:
# - postgresql: standard modern PostgreSQL URI scheme
# - postgresql+psycopg: SQLAlchemy psycopg3 driver URI
# - postgres: historical/legacy alias for postgresql retained for compatibility
ALLOWED_SCHEMES = frozenset({"postgresql", "postgresql+psycopg", "postgres"})


def _validate_and_parse_url(raw_url: str) -> URL:
    """Validate database URL scheme and parse without leaking sensitive credentials."""
    try:
        url = make_url(raw_url)
    except Exception as exc:
        raise ValueError("Invalid database URL format") from exc

    drivername = url.drivername.lower()
    if drivername not in ALLOWED_SCHEMES:
        raise ValueError(
            f"Unsupported database URL scheme '{drivername}'. Only PostgreSQL is supported "
            "(acceptable schemes: postgresql, postgresql+psycopg, or postgres legacy alias)."
        )
    return url


def normalize_psycopg_url(raw_url: str) -> str:
    """Ensure connection string uses standard postgresql:// for direct psycopg."""
    url = _validate_and_parse_url(raw_url)
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


def normalize_sqlalchemy_url(raw_url: str) -> str:
    """Ensure connection string uses postgresql+psycopg:// for SQLAlchemy 2."""
    url = _validate_and_parse_url(raw_url)
    return url.set(drivername="postgresql+psycopg").render_as_string(hide_password=False)


def check_database_connection(raw_url: str | None = None) -> dict[str, Any]:
    """Verify PostgreSQL connectivity without leaking credentials."""
    target_url = raw_url or get_settings().database_url
    if not target_url:
        return {
            "status": "error",
            "message": "DATABASE_URL is not configured",
        }

    try:
        psycopg_url = normalize_psycopg_url(target_url)
        with psycopg.connect(psycopg_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT version();")
                version_row = cur.fetchone()
                server_version = version_row[0] if version_row else "Unknown"

                cur.execute("SELECT current_database(), current_user;")
                db_row = cur.fetchone()
                db_name, user_name = db_row if db_row else ("Unknown", "Unknown")

                # Sanitize version string (e.g., 'PostgreSQL 17.7')
                ver_summary = " ".join(server_version.split()[:2])

                return {
                    "status": "ok",
                    "database": db_name,
                    "user": user_name,
                    "version": ver_summary,
                }
    except Exception as exc:
        # Mask exception message to ensure no connection credentials or passwords leak
        err_type = type(exc).__name__
        return {
            "status": "error",
            "error_type": err_type,
            "message": f"Connection verification failed ({err_type})",
        }


def get_engine():
    db_url = get_settings().database_url
    if not db_url:
        raise RuntimeError("DATABASE_URL is required to initialize database engine")
    sa_url = normalize_sqlalchemy_url(db_url)
    return create_engine(sa_url, pool_pre_ping=True)


def get_session_factory():
    engine = get_engine()
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)
