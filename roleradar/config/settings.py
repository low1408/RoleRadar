"""Runtime settings for RoleRadar."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="ROLERADAR_",
        extra="ignore",
    )

    environment: str = Field(default="development")
    database_url: str = Field(default="sqlite:///data/roleradar.sqlite3")
    log_level: str = Field(default="INFO")
    sqlite_wal: bool = Field(default=True)
    sqlite_busy_timeout_ms: int = Field(default=5000, ge=0)
    enable_experimental_sources: bool = Field(default=False)
    careers_gov_timeout_seconds: float = Field(default=20.0, ge=0)
    careers_gov_throttle_seconds: float = Field(default=1.0, ge=0)

    adzuna_app_id: str | None = Field(default=None, repr=False)
    adzuna_app_key: str | None = Field(default=None, repr=False)
    ssg_wsg_client_id: str | None = Field(default=None, repr=False)
    ssg_wsg_client_secret: str | None = Field(default=None, repr=False)
    ssg_wsg_taxonomy_url: str = Field(
        default="https://api.ssg-wsg.gov.sg/skills-framework/v1/skills",
    )
    ssg_wsg_timeout_seconds: float = Field(default=20.0, ge=0)
