"""#15 UI：`GET /` と、画面の静的ファイル。"""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

STATIC_DIR = Path(__file__).resolve().parents[2] / "app" / "static"
STATIC_FILES = ("index.html", "app.js", "style.css")
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
    [("/static/app.js", "javascript"), ("/static/style.css", "text/css")],
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


def test_static_script_does_not_use_inner_html() -> None:
    # API の値は textContent で入れる（XSS 対策。計画「変更・追加するファイル」）。
    script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

    assert "innerHTML" not in script
    assert "outerHTML" not in script
    assert "insertAdjacentHTML" not in script
    assert "document.write" not in script
