import logging

import pytest

from app.services.weather_codes import classify_weather_code

# 計画（docs/plans/03-weather-current.md 質問 4）で人間が承認した対応表。
APPROVED_TABLE: list[tuple[int, str]] = [
    (0, "clear"),
    (1, "clear"),
    (2, "partly_cloudy"),
    (3, "cloudy"),
    (45, "fog"),
    (48, "fog"),
    (51, "drizzle"),
    (53, "drizzle"),
    (55, "drizzle"),
    (56, "drizzle"),
    (57, "drizzle"),
    (61, "rain"),
    (63, "rain"),
    (65, "rain"),
    (66, "rain"),
    (67, "rain"),
    (71, "snow"),
    (73, "snow"),
    (75, "snow"),
    (77, "snow"),
    (80, "rain"),
    (81, "rain"),
    (82, "rain"),
    (85, "snow"),
    (86, "snow"),
    (95, "thunderstorm"),
    (96, "thunderstorm"),
    (99, "thunderstorm"),
]


@pytest.mark.parametrize(("code", "expected"), APPROVED_TABLE)
def test_known_codes_map_to_category(code: int, expected: str) -> None:
    assert classify_weather_code(code) == expected


@pytest.mark.parametrize("code", [-1, 4, 44, 97, 100, 1234])
def test_unknown_code_returns_unknown(code: int) -> None:
    assert classify_weather_code(code) == "unknown"


def test_unknown_code_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        classify_weather_code(1234)

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "1234" in warnings[0].getMessage()


def test_known_code_is_not_logged(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        classify_weather_code(0)

    assert caplog.records == []
