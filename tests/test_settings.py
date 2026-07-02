from roleradar.config.settings import Settings


def test_settings_defaults() -> None:
    settings = Settings()

    assert settings.environment == "development"
    assert settings.database_url.startswith("sqlite:///")
    assert settings.sqlite_busy_timeout_ms == 5000
    assert settings.enable_experimental_sources is False
    assert settings.careers_gov_timeout_seconds == 20.0
    assert settings.careers_gov_throttle_seconds == 1.0
