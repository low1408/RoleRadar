from roleradar.config.settings import Settings


def test_settings_defaults() -> None:
    settings = Settings()

    assert settings.environment == "development"
    assert settings.database_url.startswith("sqlite:///")
    assert settings.sqlite_busy_timeout_ms == 5000

