import pytest

from app.config import Settings

CACHE_ENV = ("CACHE_BACKEND", "CACHE_TTL_S", "REDIS_URL", "REDIS_TIMEOUT_S")
# 実在しない接続先と、秘密ではないダミーのパスワード。値が表示されないことの確認に使う。
DUMMY_PASSWORD = "dummy-password"
DUMMY_REDIS_URL = f"redis://:{DUMMY_PASSWORD}@localhost:6379/0"


def test_settings_defaults_match_spec(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "OPEN_METEO_BASE_URL",
        "OPEN_METEO_CONNECT_TIMEOUT_S",
        "OPEN_METEO_TOTAL_TIMEOUT_S",
        "LOG_LEVEL",
        *CACHE_ENV,
    ):
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=None)

    assert settings.open_meteo_base_url == "https://api.open-meteo.com"
    assert settings.open_meteo_connect_timeout_s == 3.0
    assert settings.open_meteo_total_timeout_s == 10.0
    assert settings.log_level == "INFO"
    # spec.md「6. キャッシュ」の TTL 15 分。Redis なしで動くよう、既定はメモリ。
    assert settings.cache_backend == "memory"
    assert settings.cache_ttl_s == 900
    assert settings.redis_url is None
    assert settings.redis_timeout_s == 1.0


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


def test_settings_read_cache_values_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CACHE_BACKEND", "redis")
    monkeypatch.setenv("CACHE_TTL_S", "60")
    monkeypatch.setenv("REDIS_URL", DUMMY_REDIS_URL)
    monkeypatch.setenv("REDIS_TIMEOUT_S", "0.5")

    settings = Settings(_env_file=None)

    assert settings.cache_backend == "redis"
    assert settings.cache_ttl_s == 60
    assert settings.redis_url is not None
    assert settings.redis_url.get_secret_value() == DUMMY_REDIS_URL
    assert settings.redis_timeout_s == 0.5


def test_settings_do_not_show_redis_url(monkeypatch: pytest.MonkeyPatch) -> None:
    # REDIS_URL はパスワードを含みうる。設定を表示・ログ出力しても値が出ないこと。
    monkeypatch.setenv("CACHE_BACKEND", "redis")
    monkeypatch.setenv("REDIS_URL", DUMMY_REDIS_URL)

    settings = Settings(_env_file=None)

    assert DUMMY_PASSWORD not in repr(settings)
    assert DUMMY_PASSWORD not in str(settings)
    assert DUMMY_PASSWORD not in settings.model_dump_json()


@pytest.mark.parametrize("redis_url", [None, ""])
def test_settings_redis_backend_requires_url(
    monkeypatch: pytest.MonkeyPatch, redis_url: str | None
) -> None:
    monkeypatch.setenv("CACHE_BACKEND", "redis")
    monkeypatch.delenv("REDIS_URL", raising=False)
    if redis_url is not None:
        monkeypatch.setenv("REDIS_URL", redis_url)

    with pytest.raises(ValueError):
        Settings(_env_file=None)


@pytest.mark.parametrize("value", ["Memory", "REDIS", "memcached", ""])
def test_settings_reject_invalid_cache_backend(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("CACHE_BACKEND", value)
    monkeypatch.setenv("REDIS_URL", DUMMY_REDIS_URL)

    with pytest.raises(ValueError):
        Settings(_env_file=None)


@pytest.mark.parametrize("name", ["CACHE_TTL_S", "REDIS_TIMEOUT_S"])
@pytest.mark.parametrize("value", ["0", "-1", "abc"])
def test_settings_reject_invalid_cache_numbers(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError):
        Settings(_env_file=None)


def test_settings_invalid_redis_url_error_does_not_show_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 検証エラーの文面に、入力された REDIS_URL の値を出さない。
    monkeypatch.setenv("CACHE_BACKEND", "memcached")
    monkeypatch.setenv("REDIS_URL", DUMMY_REDIS_URL)

    with pytest.raises(ValueError) as excinfo:
        Settings(_env_file=None)

    assert DUMMY_PASSWORD not in str(excinfo.value)
