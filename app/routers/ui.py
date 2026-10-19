"""画面（`GET /`）。表示はブラウザが API を呼んで行い、サーバーは静的ファイルを返すだけ。"""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

# 配るのはリポジトリのこのディレクトリだけ（利用者の入力からパスを作らない）。
STATIC_DIR = Path(__file__).resolve().parents[1] / "static"

router = APIRouter()


@router.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html", media_type="text/html")


@router.get("/compare", include_in_schema=False)
async def compare() -> FileResponse:
    # 気候の比較ページ（#25）。グラフは compare.js が /static/climate.json を読んで描く。
    return FileResponse(STATIC_DIR / "compare.html", media_type="text/html")
