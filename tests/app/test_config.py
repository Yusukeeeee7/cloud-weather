import pytest

from app.config import Settings

CACHE_ENV = (
    "CACHE_BACKEND",
    "CACHE_TTL_S",
    "CACHE_STALE_MAX_AGE_S",
    "REDIS_URL",
    "REDIS_TIMEOUT_S",
)
RETRY_ENV = ("OPEN_METEO_MAX_RETRIES", "OPEN_METEO_RETRY_BACKOFF_S")
# 実在しない接続先と、秘密ではないダミーのパスワード。値が表示されないことの確認に使う。
DUMMY_PASSWORD = "dummy-password"  # noqa: S105
DUMMY_REDIS_URL = f"redis://:{DUMMY_PASSWORD}@localhost:6379/0"


def test_settings_defaults_match_spec(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "OPEN_METEO_BASE_URL",
        "OPEN_METEO_CONNECT_TIMEOUT_S",
        "OPEN_METEO_TOTAL_TIMEOUT_S",
        "LOG_LEVEL",
        *CACHE_ENV,
        *RETRY_ENV,
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
    # spec.md「7. 外部API・データ」：リトライは最大 2 回。待ち時間の基準は 0.5 秒。
    assert settings.open_meteo_max_retries == 2
    assert settings.open_meteo_retry_backoff_s == 0.5
    # spec.md「6. キャッシュ」：stale は最大 6 時間前まで。
    assert settings.cache_stale_max_age_s == 21600


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


def test_settings_read_retry_and_stale_values_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPEN_METEO_MAX_RETRIES", "0")
    monkeypatch.setenv("OPEN_METEO_RETRY_BACKOFF_S", "0.1")
    monkeypatch.setenv("CACHE_STALE_MAX_AGE_S", "3600")

    settings = Settings(_env_file=None)

    assert settings.open_meteo_max_retries == 0
    assert settings.open_meteo_retry_backoff_s == 0.1
    assert settings.cache_stale_max_age_s == 3600


@pytest.mark.parametrize(
    ("name", "value"),
    [
        # リトライ回数は 0 以上で、上限（5 回）つき。
        ("OPEN_METEO_MAX_RETRIES", "-1"),
        ("OPEN_METEO_MAX_RETRIES", "6"),
        ("OPEN_METEO_MAX_RETRIES", "1.5"),
        ("OPEN_METEO_MAX_RETRIES", "abc"),
        ("OPEN_METEO_RETRY_BACKOFF_S", "0"),
        ("OPEN_METEO_RETRY_BACKOFF_S", "-1"),
        ("OPEN_METEO_RETRY_BACKOFF_S", "abc"),
        ("CACHE_STALE_MAX_AGE_S", "0"),
        ("CACHE_STALE_MAX_AGE_S", "-1"),
        ("CACHE_STALE_MAX_AGE_S", "abc"),
    ],
)
def test_settings_reject_invalid_retry_and_stale_values(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError):
        Settings(_env_file=None)


@pytest.mark.parametrize(("stale_max_age_s", "valid"), [("899", False), ("900", True)])
def test_settings_stale_max_age_must_not_be_shorter_than_ttl(
    monkeypatch: pytest.MonkeyPatch, stale_max_age_s: str, valid: bool
) -> None:
    # stale の上限が TTL より短いと、TTL 内の値が「古すぎる」ことになってしまう。
    monkeypatch.setenv("CACHE_TTL_S", "900")
    monkeypatch.setenv("CACHE_STALE_MAX_AGE_S", stale_max_age_s)

    if valid:
        assert Settings(_env_file=None).cache_stale_max_age_s == 900
    else:
        with pytest.raises(ValueError):
            Settings(_env_file=None)


# --- #8 データ取得（一括取得の設定） ---

DATA_FETCH_ENV = (
    "IEM_BASE_URL",
    "OPEN_METEO_ARCHIVE_BASE_URL",
    "DATA_FETCH_TIMEOUT_S",
    "IEM_REQUEST_INTERVAL_S",
)


def test_settings_data_fetch_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in DATA_FETCH_ENV:
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=None)

    assert settings.iem_base_url == "https://mesonet.agron.iastate.edu"
    assert settings.open_meteo_archive_base_url == "https://archive-api.open-meteo.com"
    # 1 年ぶんをまとめて取るので、全体のタイムアウトは通常（10 秒）より長い。
    assert settings.data_fetch_timeout_s == 60.0
    # IEM は同じ IP から 1 秒に 1 回まで。余裕を見て 2 秒あける。
    assert settings.iem_request_interval_s == 2.0


def test_settings_data_fetch_read_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IEM_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("OPEN_METEO_ARCHIVE_BASE_URL", "https://archive.example.invalid")
    monkeypatch.setenv("DATA_FETCH_TIMEOUT_S", "120")
    monkeypatch.setenv("IEM_REQUEST_INTERVAL_S", "3.5")

    settings = Settings(_env_file=None)

    assert settings.iem_base_url == "https://example.invalid"
    assert settings.open_meteo_archive_base_url == "https://archive.example.invalid"
    assert settings.data_fetch_timeout_s == 120.0
    assert settings.iem_request_interval_s == 3.5


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("DATA_FETCH_TIMEOUT_S", "0"),
        ("DATA_FETCH_TIMEOUT_S", "-1"),
        ("DATA_FETCH_TIMEOUT_S", "abc"),
        # IEM の制限（1 秒に 1 回）より短い間隔は受け付けない。
        ("IEM_REQUEST_INTERVAL_S", "0"),
        ("IEM_REQUEST_INTERVAL_S", "0.99"),
        ("IEM_REQUEST_INTERVAL_S", "abc"),
    ],
)
def test_settings_reject_invalid_data_fetch_values(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError):
        Settings(_env_file=None)


def test_settings_accept_minimum_iem_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IEM_REQUEST_INTERVAL_S", "1")

    assert Settings(_env_file=None).iem_request_interval_s == 1.0
