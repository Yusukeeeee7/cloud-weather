import pytest

from app.config import Settings


def test_settings_defaults_match_spec(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "OPEN_METEO_BASE_URL",
        "OPEN_METEO_CONNECT_TIMEOUT_S",
        "OPEN_METEO_TOTAL_TIMEOUT_S",
        "LOG_LEVEL",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=None)

    assert settings.open_meteo_base_url == "https://api.open-meteo.com"
    assert settings.open_meteo_connect_timeout_s == 3.0
    assert settings.open_meteo_total_timeout_s == 10.0
    assert settings.log_level == "INFO"


def test_settings_read_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPEN_METEO_CONNECT_TIMEOUT_S", "1.5")
    monkeypatch.setenv("OPEN_METEO_TOTAL_TIMEOUT_S", "4")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    settings = Settings(_env_file=None)

    assert settings.open_meteo_connect_timeout_s == 1.5
    assert settings.open_meteo_total_timeout_s == 4.0
    assert settings.log_level == "DEBUG"


@pytest.mark.parametrize("value", ["0", "-1", "abc"])
def test_settings_reject_invalid_timeout(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("OPEN_METEO_TOTAL_TIMEOUT_S", value)

    with pytest.raises(ValueError):
        Settings(_env_file=None)


@pytest.mark.parametrize("value", ["debug", "VERBOSE", ""])
def test_settings_reject_invalid_log_level(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("LOG_LEVEL", value)

    with pytest.raises(ValueError):
        Settings(_env_file=None)
