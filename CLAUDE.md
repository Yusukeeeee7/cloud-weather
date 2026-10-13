# CLAUDE.md

このファイルは Claude Code が毎回読み込むプロジェクトの指示書です。短く、守るべきことだけを書きます。
詳細な仕様は `docs/spec.md` を参照してください。

## プロジェクト概要

- 外部天気API（Open-Meteo）を呼び、必要な項目だけ整形して返す自作API
- 空港観測（METAR）を使った **雲底高度の予測モデル**（東京 RJTT / ベルリン EDDB）
- キャッシュ、Discord通知、Docker、CI/CD を含む 1 リポジトリ構成
- 目的：外部API連携・キャッシュ・ML・CI/CD・AI駆動開発の学習と記録

## 技術スタック

Python 3.14 / uv / FastAPI / httpx / pydantic-settings / Redis / pandas / LightGBM / Jupyter /
pytest / respx / nbmake / ruff / mypy / Docker / docker compose / GitHub Actions

## ディレクトリ

```
app/          FastAPI（routers/, services/, clients/, cache/, notify/）
ml/           ノートブックとAPIで共有するコード（features.py など）
notebooks/    01_data_fetch → 02_eda → 03_baseline → 04_train → 05_evaluate → 06_error_analysis → 07_improve → 08_evaluate_improved
data/         生データ・加工データ（git管理外。01 で再取得できる）
models/       学習済みモデル
reports/      評価指標（metrics.json など）
tests/        app/ と ml/ のテスト、fixtures/（外部APIの保存済みレスポンス）
docs/         spec.md / dev-log.md / plans/ / eda.md / model-card.md / features/
.claude/      skills と settings
```

## コマンド

```bash
uv sync                                   # 依存インストール
uv run uvicorn app.main:app --reload      # API起動
uv run pytest                             # テスト
uv run pytest --cov=app --cov=ml          # カバレッジ付き
uv run pytest --nbmake notebooks/         # ノートブックの実行確認（サンプルデータ）
uv run ruff check . && uv run ruff format --check .
uv run mypy app ml
docker compose up --build                 # API + Redis

# pandas を読み込めない PC（Windows のアプリケーション制御ポリシー）では、テスト類を Docker の中で実行する
docker build -f Dockerfile.dev -t cloud-weather-dev .
docker run --rm -v "${PWD}:/work" cloud-weather-dev uv run --locked pytest --cov=app --cov=ml
```

## 開発の進め方（必須）

1. **1タスク = 1機能 = 1ブランチ = 1PR**。ブランチ名は `feature/issues_<issue番号>`。
2. **実装前に計画を `docs/plans/` に書き、承認を待つ**。承認済みの計画がない機能は実装しない。
3. **TDD**：Red → Green → Refactor。テストを先に書き、失敗することを実行して確認してから実装する。
4. **完了条件**：テスト・lint・型チェックがすべて通り、`docs/spec.md` の該当機能の受け入れ条件を満たすこと。
5. skills を使う：計画は `/plan-feature`、実装は `/implement-feature`、PR前は `/review`、機能説明は `/explain-feature`、完了後は `/dev-log`。
6. `docs/spec.md` にない仕様を勝手に追加しない。不明点は推測せず質問する。

## コーディング規約

- 型ヒント必須。関数は小さく、1つの責務にする。
- 外部APIの呼び出しは `app/clients/` に集約し、**タイムアウトを必ず指定**する。
- 設定値は環境変数から `pydantic-settings` で読む。コードに直書きしない。
- 時刻は内部ではすべて UTC。表示時のみローカル時刻に変換する。日単位のデータは現地の日付で区切る。
- テストの期待値（太陽計算の時刻など）をAIが自分で計算して作らない。外部の信頼できる値を fixtures に保存して使う。
- 単位はメートル・摂氏で統一（METARの雲高はフィートなので変換する）。
- テストで外部APIを実際に呼ばない。`respx` でモックし、実レスポンスは `tests/fixtures/` に保存して使う。

## ノートブック

- 番号順に、上から再実行すれば同じ結果になること。乱数シードは固定する。
- 特徴量作成は `ml/features.py` に書き、ノートブックとAPIの両方から import する（学習と推論のずれを防ぐ）。
- 成果物はファイルに保存する：`data/processed/`、`models/`、`reports/metrics.json`。
- `02_eda.ipynb` 以外は出力を消してコミットする（nbstripout）。

## 外部API・データ（ハルシネーション対策）

- Open-Meteo / METAR のパラメータ名・レスポンス項目を **推測で書かない**。
- 使ってよいのは `docs/spec.md` の「外部API」表で **確認済み** になっているものだけ。
  未確認のものが必要になったら、作業を止めて人間に公式ドキュメントでの確認を依頼する。
- ライブラリのAPIも、不確かなら実際にコードを実行して確かめてから使う。

## セキュリティ（必須）

- シークレット（APIキー、Discord Webhook URL など）をコード・ログ・テスト・コミットに含めない。
- `.env` は git 管理外。必要な変数は `.env.example` に名前だけ書く。`.env` は読まない。
- 入力値は必ず検証する：`city` は許可リスト、数値は範囲チェック。
- ユーザー入力から外部URLを組み立てない。通信先は spec に定めたホストのみ。
- 依存パッケージを追加するときは、理由を説明して承認を得る。
- 破壊的な操作（`git push --force`、`rm -rf`、ブランチ削除、履歴の書き換え）はしない。

## やらないこと

- main への直接コミット
- テストを通すためにテストを弱める・skip する・期待値を実装に合わせて書き換える
- 1つのPRで複数機能をまとめて変更する
