"""#15 UI：`GET /` と、画面の静的ファイル。#25 の `GET /compare` も。"""

import json
import math
import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

STATIC_DIR = Path(__file__).resolve().parents[2] / "app" / "static"
STATIC_FILES = ("index.html", "app.js", "style.css", "compare.html", "compare.js")
# 出典の表示（CC BY 4.0。spec.md 7 の表）。
ATTRIBUTION_URL = "https://open-meteo.com/"
# SVG の名前空間（要素を作るときの識別子で、通信先ではない）。
SVG_NAMESPACE = "http://www.w3.org/2000/svg"
_URL = re.compile(r"""(?:https?:)?//[^\s"'`<>()]+""")


def test_root_returns_html(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<title>" in response.text


def test_root_has_open_meteo_attribution(client: TestClient) -> None:
    response = client.get("/")

    assert f'href="{ATTRIBUTION_URL}"' in response.text
    assert "Open-Meteo" in response.text


def test_root_loads_script_and_style_from_static(client: TestClient) -> None:
    response = client.get("/")

    assert 'src="/static/app.js"' in response.text
    assert 'href="/static/style.css"' in response.text


@pytest.mark.parametrize(
    ("path", "content_type"),
    [
        ("/static/app.js", "javascript"),
        ("/static/style.css", "text/css"),
        ("/static/compare.js", "javascript"),
        ("/static/climate.json", "application/json"),
    ],
)
def test_static_files_served(client: TestClient, path: str, content_type: str) -> None:
    response = client.get(path)

    assert response.status_code == 200
    assert content_type in response.headers["content-type"]
    # 改行（CRLF・LF）も含めて、ファイルのまま返す。
    assert response.content == (STATIC_DIR / path.removeprefix("/static/")).read_bytes()


@pytest.mark.parametrize(
    "path",
    [
        "/static/../config.py",
        "/static/%2e%2e/config.py",
        "/static/..%2fconfig.py",
        "/static/%2e%2e%2fconfig.py",
        "/static/..%5cconfig.py",
        "/static/../../pyproject.toml",
        "/static/%2e%2e/%2e%2e/pyproject.toml",
    ],
)
def test_static_path_traversal_rejected(client: TestClient, path: str) -> None:
    response = client.get(path)

    assert response.status_code == 404
    assert "class Settings" not in response.text
    assert "[project]" not in response.text


def test_static_missing_file_is_404(client: TestClient) -> None:
    assert client.get("/static/missing.js").status_code == 404


@pytest.mark.parametrize("name", STATIC_FILES)
def test_static_has_no_external_hosts(name: str) -> None:
    # CDN・Web フォント・地図のタイルなどを読まない。リンクは出典だけ。
    text = (STATIC_DIR / name).read_text(encoding="utf-8")

    urls = set(_URL.findall(text))

    assert urls <= {ATTRIBUTION_URL, SVG_NAMESPACE}


@pytest.mark.parametrize("name", ["app.js", "compare.js"])
def test_static_script_does_not_use_inner_html(name: str) -> None:
    # API の値は textContent で入れる（XSS 対策。計画「変更・追加するファイル」）。
    script = (STATIC_DIR / name).read_text(encoding="utf-8")

    assert "innerHTML" not in script
    assert "outerHTML" not in script
    assert "insertAdjacentHTML" not in script
    assert "document.write" not in script


# #25 の追加 3：読み込み中の表示。
# 画面の動きは人間がブラウザで確かめる。ここでは部品があることだけを見る。
def test_app_script_shows_loading_state() -> None:
    script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

    assert "読み込み中…" in script
    assert '"aria-busy"' in script
    assert '"status"' in script


def test_app_script_shows_hourly_wind_speed() -> None:
    # 追加 2 の⑤：24 時間の予報の表に、1 時間ごとの風速の列。
    script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

    assert "hour.wind_speed_ms" in script


def test_app_script_has_retry_button() -> None:
    script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

    assert "もう一度読み込む" in script


def test_spinner_stops_when_reduced_motion() -> None:
    # 動きを減らす設定では、くるくるを回さない（文字だけにする）。
    style = (STATIC_DIR / "style.css").read_text(encoding="utf-8")
    reduced = style.split("@media (prefers-reduced-motion: reduce)", 1)

    assert ".spinner" in reduced[0]
    assert len(reduced) == 2
    assert ".spinner" in reduced[1]
    assert "animation: none" in reduced[1]


# #25 気候の比較ページ（`GET /compare`）。
CLIMATE_JSON = STATIC_DIR / "climate.json"
CLIMATE_CITIES = {"tokyo", "berlin"}
CLIMATE_YEARS = list(range(2018, 2026))


def test_compare_returns_html(client: TestClient) -> None:
    response = client.get("/compare")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert 'src="/static/compare.js"' in response.text
    assert 'href="/static/style.css"' in response.text
    assert 'href="/"' in response.text
    assert f'href="{ATTRIBUTION_URL}"' in response.text


def test_root_links_to_compare(client: TestClient) -> None:
    assert 'href="/compare"' in client.get("/").text


def test_compare_not_in_openapi(client: TestClient) -> None:
    # 画面は API の一覧に載せない（DAST が取り込む道の数を変えない）。
    paths = client.get("/openapi.json").json()["paths"]

    assert "/compare" not in paths
    assert "/" not in paths


def test_compare_has_dew_point_chart(client: TestClient) -> None:
    # 追加 2 の③：月ごとの平均の露点（METAR）の折れ線。
    text = client.get("/compare").text

    assert 'id="dew-chart"' in text
    assert '"dew_point_c_metar"' in (STATIC_DIR / "compare.js").read_text(encoding="utf-8")


def test_compare_has_wind_speed_chart(client: TestClient) -> None:
    # 追加 2 の④：月ごとの平均風速（再解析）の折れ線。
    text = client.get("/compare").text

    assert 'id="wind-chart"' in text
    assert '"wind_speed_ms_reanalysis"' in (STATIC_DIR / "compare.js").read_text(encoding="utf-8")


def test_compare_has_wet_total(client: TestClient) -> None:
    # 雨の日数のグラフの下に、1 年あたりの合計を出す欄。
    assert 'id="wet-total"' in client.get("/compare").text


def test_compare_script_reads_only_climate_json() -> None:
    # 外部 API・ほかの API を呼ばず、同じオリジンの静的な JSON だけを読む。
    script = (STATIC_DIR / "compare.js").read_text(encoding="utf-8")

    assert '"/static/climate.json"' in script
    assert script.count("fetch(") == 1


def _climate() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(CLIMATE_JSON.read_text(encoding="utf-8"))
    return data


def test_climate_json_was_made_from_full_data() -> None:
    data = _climate()

    assert data["mode"] == "full"
    assert data["source"] == "data/processed/observations.parquet"
    assert data["period"] == {"start": "2018-01-01", "end": "2025-12-31", "dates": "local"}
    assert set(data["cities"]) == CLIMATE_CITIES


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


@pytest.mark.parametrize("city", sorted(CLIMATE_CITIES))
def test_climate_json_matches_schema(city: str) -> None:
    data = _climate()["cities"][city]

    monthly = data["monthly"]
    assert [row["month"] for row in monthly] == list(range(1, 13))
    for row in monthly:
        assert all(_is_number(row[name]) for name in row)
        assert -40 <= row["temperature_c_metar"] <= 45
        assert -40 <= row["temperature_c_reanalysis"] <= 45
        # 露点は気温より高くならない（月の平均どうしでも）。
        assert -60 <= row["dew_point_c_metar"] <= row["temperature_c_metar"]
        assert 0 <= row["wind_speed_ms_reanalysis"] <= 30
        assert 0 <= row["wet_days_1mm"] <= 31
        assert 0 <= row["precipitation_observed_days"] <= 31
        assert 0 <= row["low_ceiling_share"] <= 1
    # 追加：1 mm 以上の雨の日数の、1 年あたりの合計。
    # 月の値（小数 1 桁に丸めたもの）の合計とは、丸めのぶんだけずれうる。
    total = data["wet_days_1mm_per_year"]
    assert _is_number(total)
    assert 0 <= total <= 366
    assert abs(total - sum(row["wet_days_1mm"] for row in monthly)) <= 0.6

    yearly = data["yearly"]
    assert [row["year"] for row in yearly] == CLIMATE_YEARS
    for row in yearly:
        assert all(_is_number(row[name]) for name in row)
        assert row["precipitation_mm"] >= 0
        assert 300 <= row["complete_days"] <= 366
        assert 0 <= row["metar_auto_share"] <= 1

    share = data["cloud_cover_share"]
    assert list(share) == ["0-25", "25-50", "50-75", "75-100"]
    assert all(_is_number(value) and 0 <= value <= 1 for value in share.values())
    assert sum(share.values()) == pytest.approx(1, abs=0.002)


def test_climate_json_has_no_local_paths() -> None:
    text = CLIMATE_JSON.read_text(encoding="utf-8")

    # "/tmp" は一時ファイルを使うのではなく、JSON に入っていないことを確かめる文字列。
    for word in ("C:\\", "/home/", "/Users/", "/work", "/tmp"):  # noqa: S108
        assert word not in text
