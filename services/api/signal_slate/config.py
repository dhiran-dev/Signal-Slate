"""Application configuration settings for Signal Slate."""

import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def get_default_env_file() -> Path | None:
    """Resolve configuration file path.

    Checks SIGNAL_SLATE_ENV_FILE override first (returning the specified path);
    falls back to ~/.config/signal-slate/app.env only when no override is set.
    """
    if "SIGNAL_SLATE_ENV_FILE" in os.environ:
        override = os.environ["SIGNAL_SLATE_ENV_FILE"]
        return Path(override).expanduser() if override else None

    default_path = Path.home() / ".config" / "signal-slate" / "app.env"
    return default_path if default_path.is_file() else None


class Settings(BaseSettings):
    google_cloud_project: str = "balmy-coral-508014-p7"
    google_cloud_location: str = "global"
    google_genai_use_vertexai: bool = True
    gemini_model: str = "gemini-2.5-flash"
    database_url: str | None = None
    app_origin: str = "http://localhost:5173"
    evidence_storage_path: str = "./data"
    max_sessions_per_day: int = 20
    max_model_turns_per_workflow: int = 5
    max_output_tokens: int = 1024

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        extra="ignore",
    )


def get_settings() -> Settings:
    settings = Settings(_env_file=get_default_env_file())  # type: ignore[call-arg]
    if settings.google_genai_use_vertexai:
        os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "true"
    if settings.google_cloud_project:
        os.environ["GOOGLE_CLOUD_PROJECT"] = settings.google_cloud_project
    if settings.google_cloud_location:
        os.environ["GOOGLE_CLOUD_LOCATION"] = settings.google_cloud_location
    return settings
