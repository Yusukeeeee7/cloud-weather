# 計画：#1 雛形（Issue #1）

状態：承認済み

## 目的と受け入れ条件

spec.md「14. 機能一覧」より：

> | 1 | 雛形 | `/health` が 200、pytest・ruff・mypy が通る、Dockerfile でビルドできる |

spec.md「5. API仕様」より：

> ### `GET /health`
> `{"status": "ok"}` を返す。

関連する要件（spec.md 11 / CLAUDE.md）：

- Docker：slim ベースイメージ、非 root ユーザーで実行、不要なファイルは `.dockerignore`
- `.env` は git 管理外、`.env.example` を用意
- 依存は `uv.lock` で固定
- Python は **3.14**（2026-10-12 に人間が決定。CLAUDE.md の「Python 3.12」から変更）

完了の確認方法：

1. `uv run pytest --cov=app --cov=ml` が通る
2. `uv run ruff check . && uv run ruff format --check .` が通る
3. `uv run mypy app ml` が通る
4. `docker build -t cloud-weather .` が成功し、コンテナを起動して `GET /health` が 200 `{"status":"ok"}` を返す（手動確認。自動化は #2 CI / #14 CD）

## 今回やらないこと

- CI（`ci.yml`）、カバレッジ 80% の強制、pip-audit、Dependabot → #2
- `/weather`、`/daylight`、`/cloud-base`、共通エラー形式（`{"error": {...}}`）→ #3 以降
- 設定読み込み（`pydantic-settings`）、構造化ログ（JSON）→ #3 で導入（#1 には読む設定値も出すログもなく、使われないコードになるため）
- Redis、`docker-compose.yml` → #5
- `app/services/`、`app/clients/`、`app/cache/`、`app/notify/` の空ディレクトリ作成（使う機能で作る）
- ノートブック関連（nbmake、nbstripout、pandas、LightGBM、Jupyter）→ #8 以降
- README の作成（spec にないため）

## 変更・追加するファイル

| ファイル | 内容 |
|---|---|
| `pyproject.toml` | プロジェクト定義（`requires-python = ">=3.14,<3.15"`）、依存、ruff / mypy / pytest の設定 |
| `.python-version` | `3.14` |
| `uv.lock` | `uv sync` で生成しコミットする |
| `app/__init__.py` | 空 |
| `app/main.py` | `FastAPI` アプリを作り、health ルーターを登録する |
| `app/routers/__init__.py` | 空 |
| `app/routers/health.py` | `GET /health` → `{"status": "ok"}`（レスポンスモデルは pydantic で型付け） |
| `ml/__init__.py` | 空（`mypy app ml` と `--cov=ml` が対象ディレクトリなしで失敗しないようにするため） |
| `tests/__init__.py`, `tests/app/__init__.py` | 空 |
| `tests/app/test_health.py` | 下のテスト一覧 |
| `Dockerfile` | `python:3.14-slim`、uv で `uv.lock` どおりに本番依存のみインストール、非 root ユーザー、`uvicorn app.main:app --host 0.0.0.0 --port 8000` |
| `.dockerignore` | `.git`, `.venv`, `.env*`, `data/`, `tests/`, `docs/`, `notebooks/`, `.claude/`, 各種キャッシュ |
| `.env.example` | 現時点では変数なし（コメントのみ）。変数を追加した機能で名前を追記する |
| `.gitignore` | `.coverage`, `htmlcov/` を追加 |
| `docs/spec.md` | 機能一覧 #1 の「状態」を更新（実装完了時） |
| `CLAUDE.md` | 技術スタックの「Python 3.12」を「Python 3.14」に変更 |

ツール設定の方針（`pyproject.toml`）：

- ruff：`target-version = "py314"`、`line-length = 100`、ルールは次の 5 つ
  - `E`（書き方の誤り）、`F`（未使用の import・未定義の名前）：ruff の基本
  - `I`（import の並び順を自動整理）
  - `B`（バグになりやすい書き方の検出）
  - `UP`（古い書き方を新しい Python の書き方へ自動修正）
- mypy：`strict = true`、`python_version = "3.14"`
  - 設定は 1 行で済み、CLAUDE.md の「型ヒント必須」を機械的に確認できる。後から strict にすると修正が溜まるため、最初から有効にする。
- pytest：`testpaths = ["tests"]`

## テスト一覧（先に書く順）

| # | テスト名 | 種類（正常/異常/境界） | 確かめること |
|---|---|---|---|
| 1 | `test_health_returns_200` | 正常 | `GET /health` のステータスが 200 |
| 2 | `test_health_returns_status_ok` | 正常 | ボディが `{"status": "ok"}` と完全一致（余計なキーがない） |
| 3 | `test_health_content_type_is_json` | 正常 | `Content-Type` が `application/json` |
| 4 | `test_health_rejects_post` | 異常 | `POST /health` は 405（GET のみ公開している） |

- `fastapi.testclient.TestClient` を使う。外部通信はない。
- Red の確認：`app/` を作る前にテストを実行し、import エラーで失敗することを確認する。
- Dockerfile はユニットテストの対象外。上の「完了の確認方法 4」で手動確認する。

## 追加する依存パッケージ

| パッケージ | 区分 | 理由 | 代替案 |
|---|---|---|---|
| `fastapi` | 本番 | API フレームワーク（CLAUDE.md の技術スタック） | なし |
| `uvicorn` | 本番 | ASGI サーバー（CLAUDE.md の起動コマンド） | `uvicorn[standard]`（uvloop 等が入るが今回は不要） |
| `pytest` | dev | テスト | なし |
| `pytest-cov` | dev | `--cov` オプション（CLAUDE.md のコマンド） | `coverage` を直接使う |
| `httpx` | dev | `TestClient` の動作に必要。#3 で外部API呼び出しに使う時点で本番依存へ移す | なし |
| `ruff` | dev | lint / format | なし |
| `mypy` | dev | 型チェック | なし |

技術スタックにある他のパッケージ（pydantic-settings, redis, respx, pandas, lightgbm, jupyter, nbmake）は、使う機能の計画で追加する。

## セキュリティ上の注意

- 入力検証：`/health` は入力を受け取らない。
- シークレット：扱わない。`.env.example` には値を書かない。`.dockerignore` で `.env*` をイメージに入れない。
- 外部通信（ホスト・タイムアウト）：アプリからの外部通信なし。ビルド時のみ PyPI と、ベースイメージ・uv の取得先（Docker Hub / ghcr.io）に接続する。
- Docker：slim イメージ、非 root ユーザー（`USER` 指定）、ベースイメージと uv のバージョンはタグで固定する。

## リスク・未決事項

- Dockerfile での uv の入れ方（公式イメージからのバイナリコピー、`uv sync --frozen --no-dev`）は、記憶で書かず uv 公式ドキュメントを確認し、実際にビルドして確かめる。
- Python 3.14 に未対応の依存があると後の機能で詰まる可能性がある。#1 の依存は `uv sync` で確認する。pandas / LightGBM などは #8 の計画時に対応状況を確認する。
- FastAPI / uvicorn のバージョンは `uv add` 時点の最新を採用し、`uv.lock` で固定する。
- Windows 上の開発なので、改行コード（CRLF）が `ruff format --check` や Docker ビルドに影響しないか実装時に確認する。

## ブロッカー（人間の対応が必要なこと）

- 解決済み：Docker デーモンの起動（2026-10-12 の実装時に起動を確認し、ビルドとコンテナでの `/health` 確認まで完了）。
- 解決済み：uv 0.13.0 を winget でインストール済み（2026-10-12）。Python は既存の 3.14.6 を使う。
- 外部API表の「未確認」項目は、この機能では使わないためブロッカーではありません。

## 質問

未回答：

1. Issue #1 の本文を読めていません（`gh` コマンドがなく、リポジトリが非公開のため Web からも読めない）。spec の機能 #1 と同じ内容という前提で実装しました。PR を出す前に、Issue に追加の要件がないか人間が確認する。

回答済み（2026-10-12）：

- 依存パッケージは最小構成にする。
- `pydantic-settings` と構造化ログは #3 で導入する（推奨に一任）。
- mypy / ruff は上の「ツール設定の方針」のとおり（推奨に一任）。

## 実装時の変更

- **Dockerfile をマルチステージにした**：uv はビルド用ステージだけで使い、実行用イメージには `.venv` と `app/`・`ml/` だけをコピーする。実行用イメージに uv を残さないため（イメージを小さくし、不要なツールを入れない）。
- **dev 依存の除外は `UV_NO_DEV=1`、ロックの確認は `uv sync --locked` にした**：計画では `uv sync --frozen --no-dev` と書いたが、uv 公式ドキュメント（Docker ガイド）を確認し、そこに書かれている方法に合わせた。`--locked` は `uv.lock` が古い場合にビルドを失敗させる。
- **ベースイメージと uv のバージョン固定**：`python:3.14-slim`、`ghcr.io/astral-sh/uv:0.13.0`（タグで固定。ダイジェスト固定は行っていない）。
- **`.env.example` は使う時点までコメントのみ**：計画どおり。
- **未対応の警告（#3 の計画で判断する）**：`StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated; install httpx2 instead.` が出る。`httpx2` は計画にない依存のため追加していない。#3（httpx を本番依存にする機能）の計画時に、`httpx2` の素性と `respx` の対応状況を公式ドキュメントで確認し、移行するか決める。
- **レビュー後の変更：自動ドキュメントを仕様に追加**：FastAPI が既定で公開する `/docs`・`/redoc`・`/openapi.json` は spec になかった。開発中の確認に使うため残すことにし、spec.md「5. API仕様」に追記した（コードの変更はなし）。
- **mypy が 1 回だけ起動に失敗した**：Windows のアプリケーション制御ポリシーが mypy の依存（`librt` の `base64` DLL）の読み込みをブロックした。再実行では成功し、以後は再現していない。
