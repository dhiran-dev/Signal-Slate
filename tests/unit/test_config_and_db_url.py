"""Focused unit tests for database URL validation and configuration resolution.

Verifies:
1. Rejection of arbitrary non-PostgreSQL schemes (mysql, sqlite, oracle, etc.).
2. Acceptance of postgresql, postgresql+psycopg, and legacy postgres alias.
3. Credential safety during URL validation and database connection checks.
4. Config resolution using Path.home()/.config/signal-slate/app.env and SIGNAL_SLATE_ENV_FILE.
"""

from pathlib import Path

import pytest
from signal_slate.config import get_default_env_file, get_settings
from signal_slate.db import (
    check_database_connection,
    normalize_psycopg_url,
    normalize_sqlalchemy_url,
)


def test_normalize_psycopg_url_valid_schemes():
    """Valid PostgreSQL schemes and legacy alias are normalized to postgresql://."""
    url1 = "postgresql://mixer:pass123@localhost:5432/signal_slate"
    url2 = "postgresql+psycopg://mixer:pass123@localhost:5432/signal_slate"
    url3 = "postgres://mixer:pass123@localhost:5432/signal_slate"

    expected = "postgresql://mixer:pass123@localhost:5432/signal_slate"
    assert normalize_psycopg_url(url1) == expected
    assert normalize_psycopg_url(url2) == expected
    assert normalize_psycopg_url(url3) == expected


def test_normalize_sqlalchemy_url_valid_schemes():
    """Valid PostgreSQL schemes and legacy alias are normalized to postgresql+psycopg://."""
    url1 = "postgresql://mixer:pass123@localhost:5432/signal_slate"
    url2 = "postgresql+psycopg://mixer:pass123@localhost:5432/signal_slate"
    url3 = "postgres://mixer:pass123@localhost:5432/signal_slate"

    expected = "postgresql+psycopg://mixer:pass123@localhost:5432/signal_slate"
    assert normalize_sqlalchemy_url(url1) == expected
    assert normalize_sqlalchemy_url(url2) == expected
    assert normalize_sqlalchemy_url(url3) == expected


@pytest.mark.parametrize(
    "invalid_url",
    [
        "mysql://user:supersecret@localhost:3306/db",
        "mysql+pymysql://user:supersecret@localhost:3306/db",
        "sqlite:///data/test.db",
        "sqlite+pysqlite:///data/test.db",
        "oracle://user:supersecret@localhost:1521/db",
        "mssql+pyodbc://user:supersecret@localhost/db",
        "mongodb://user:supersecret@localhost:27017/db",
    ],
)
def test_reject_arbitrary_database_schemes(invalid_url: str):
    """Arbitrary non-PostgreSQL drivers must be rejected with ValueError."""
    with pytest.raises(ValueError) as excinfo_psycopg:
        normalize_psycopg_url(invalid_url)
    assert "Only PostgreSQL is supported" in str(excinfo_psycopg.value)
    # Ensure sensitive credentials are never leaked in the exception message
    assert "supersecret" not in str(excinfo_psycopg.value)

    with pytest.raises(ValueError) as excinfo_sa:
        normalize_sqlalchemy_url(invalid_url)
    assert "Only PostgreSQL is supported" in str(excinfo_sa.value)
    assert "supersecret" not in str(excinfo_sa.value)


def test_check_database_connection_credential_safety_on_invalid_scheme():
    """Connection check with invalid scheme returns safe failure without leaking credentials."""
    result = check_database_connection("mysql://app_user:ultra_private_pass@localhost:3306/db")
    assert result["status"] == "error"
    assert result["error_type"] == "ValueError"
    assert "Connection verification failed" in result["message"]
    # Ensure credentials and sensitive info are not in any field
    result_str = str(result)
    assert "ultra_private_pass" not in result_str
    assert "app_user" not in result_str


def test_config_default_external_env_resolution(monkeypatch):
    """Default config resolves to user home directory."""
    monkeypatch.delenv("SIGNAL_SLATE_ENV_FILE", raising=False)
    resolved = get_default_env_file()
    expected_default = Path.home() / ".config" / "signal-slate" / "app.env"
    if expected_default.is_file():
        assert resolved == expected_default
    else:
        assert resolved is None


def test_config_explicit_override_resolution(tmp_path, monkeypatch):
    """SIGNAL_SLATE_ENV_FILE explicitly overrides default config path."""
    override_env = tmp_path / "custom.env"
    override_env.write_text(
        "DATABASE_URL=postgresql://fake_user:fake_pass@localhost:5432/fake_db\n"
    )

    monkeypatch.setenv("SIGNAL_SLATE_ENV_FILE", str(override_env))
    assert get_default_env_file() == override_env

    settings = get_settings()
    assert settings.database_url == "postgresql://fake_user:fake_pass@localhost:5432/fake_db"


def test_config_override_isolation_with_fake_config(tmp_path, monkeypatch):
    """Override isolation: explicit override isolates from default config path.

    Uses temporary fake configurations only; never accesses real secrets.
    """
    fake_config = tmp_path / "isolated_fake.env"
    fake_config.write_text(
        "DATABASE_URL=postgresql://fake_isolated_user:fake_pass@localhost:5432/fake_isolated_db\n"
    )

    monkeypatch.setenv("SIGNAL_SLATE_ENV_FILE", str(fake_config))
    settings = get_settings()
    assert (
        settings.database_url
        == "postgresql://fake_isolated_user:fake_pass@localhost:5432/fake_isolated_db"
    )


def test_config_invalid_override_does_not_fallback(tmp_path, monkeypatch):
    """An invalid/nonexistent override cannot fall back to default external credential file."""
    nonexistent_override = tmp_path / "does_not_exist.env"
    monkeypatch.setenv("SIGNAL_SLATE_ENV_FILE", str(nonexistent_override))

    settings = get_settings()
    # Must NOT fall back to any credential file in ~/.config/signal-slate/app.env
    assert settings.database_url is None


def test_config_empty_override_does_not_fallback(monkeypatch):
    """An empty override string results in None.

    Does not fall back to default credential file.
    """
    monkeypatch.setenv("SIGNAL_SLATE_ENV_FILE", "")
    assert get_default_env_file() is None

    settings = get_settings()
    assert settings.database_url is None
