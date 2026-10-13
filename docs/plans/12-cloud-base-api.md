# 計画：#12 推論API（Issue #23）

状態：承認済み（2026-10-13。質問 1〜10 はすべて推奨のとおり）

## 目的と受け入れ条件

spec.md「14. 機能一覧」より：

> | 12 | 推論API | `/cloud-base` が仕様どおりに返る。モデルなしで 503 |

spec.md「5. API仕様」より：

> ### `GET /cloud-base?city=tokyo`
>
> ```json
> {
>   "city": "tokyo",
>   "valid_at": "2026-10-12T03:00:00Z",
>   "predicted_m": 850,
>   "baseline_m": 760,
>   "model_version": "2026-10-xx-lgbm-v1"
> }
> ```
>
> `baseline_m` は概算式 `125 × (気温 − 露点)` による値。
>
> | 503 | `model_unavailable` | モデルファイルが読み込めない |

spec.md のほかの節にある、#12 で決める・確かめると書かれたこと：

- 7 の表：予報の `hourly=` の `pressure_msl` は「未使用・未確認（#12 で確認する）」。取れなければ、その特徴量を外して学習し直す（9「#11 で決めたこと」）。
- 9：API のイメージに `lightgbm`・`joblib`（と pandas）をどう入れるか。
- 9：`/cloud-base` の `baseline_m` を 0〜1,524 m に収めるかどうか。
- 9：joblib のファイルは、決まったパスのものだけを読む（利用者の入力・環境変数からパスを作らない）。
- 9：特徴量作成は `ml/features.py` のみ。学習と推論で共有する。

#11 からの申し送り（`docs/dev-log.md`）：成功基準に届いていないモデルを `/cloud-base` でどう出すか（質問 6）。

完了の確認方法：

1. `Dockerfile.dev` のイメージの中で `uv run --locked pytest --cov=app --cov=ml` が通る（カバレッジ 80% 以上）
2. 同じく `ruff check .`・`ruff format --check .`・`mypy app ml`・`pip-audit`・`pytest --nbmake notebooks/` が通る
3. `docker build .`（API のイメージ）が通り、`docker compose up --build` で `/cloud-base?city=tokyo`・`?city=berlin` が 200 を返す（手動確認。Open-Meteo を 2 回呼ぶ）
4. 同じイメージで、モデルのファイルを読めない状態にすると `/cloud-base` が 503 `model_unavailable`、`/weather`・`/daylight`・`/health` は 200 のまま
5. 既存の `/weather`・`/daylight` のテストが、期待値を変えずに通る（変えるのは、外部APIに送る `hourly` の一覧を確かめる 1 か所だけ。下の「テスト一覧」の注）
6. spec 5・7・9 に今回決めたことを追記し、機能一覧 #12 を完了にする
7. PR で CI が通る

## 今回やらないこと

- モデル・特徴量・成功基準の変更、学習のやり直し（`pressure_msl` が予報で取れないと分かった場合を除く。そのときは作業を止めて報告する。リスク 1）
- 未来の時刻の予測（何時間後の雲底）、複数の時刻の一覧。返すのは 1 つの時刻だけ
- 応答への項目の追加（`cached`・`stale`・上限・信頼区間など。spec の 5 項目だけ。質問 5・6）
- 学習と推論の入力の差を測ること（過去の予報のデータが要る。spec 7 で未確認）
- Discord 通知（#13）、CD（#14）、UI（#15）
- `/weather` の応答・キャッシュの決まりの変更（外部APIに送る `hourly` の項目が増えるだけ）
- モデルのファイルの SHA-256 の記録、`.gitattributes`（#11 で見送ったもの。別の Issue）

## 設計の要点

### どの時刻の、どの値で予測するか

- 入力は、`/weather` と同じ 1 回の外部呼び出し（`/v1/forecast`）の **`hourly` の 1 行**。`current` は使わない。
  - 理由：学習は「正時の値」「降水量は前の 1 時間の合計」。`current` は 15 分おき（保存済みの応答で `interval: 900`）で、降水量の区切りが学習と違う見込み。`pressure_msl` も `current` では未確認。
- そのために、外部APIに送る `hourly=` に 4 項目を足す：`dew_point_2m`、`relative_humidity_2m`、`pressure_msl`、`wind_speed_10m`。**4 つとも、予報の `hourly` としては spec 7 で未確認**（ブロッカー 1）。
- `valid_at` は **現在以前の、最も近い正時**（現在が 13:41 なら 13:00。正時ちょうどならその時刻）。質問 1。
  - `hourly` は現地の今日 0 時から入っているので（spec 7、確認済み）、この行はいつもある。なければ 502。
- その行の値を、`ml/archive.py` の `VARIABLES` と同じ対応で列の名前に直し（`temperature_2m` → `temperature_c` など）、1 行の表にして `ml/features.py` の `features` に渡す。特徴量の式は API の側に書かない。
- 予測は `ml/model.py` の `predict_m`（0〜1,524 m に収まる）。ベースラインは `ml/baseline.py`（質問 3）。
- その行の項目が欠けている・null・型が違う場合は 502 `upstream_error`（`/weather` と同じ。欠損のまま予測しない）。

### キャッシュ・stale

- `/weather` と同じキー（`weather:{city}`）・同じ TTL・同じ stale の決まりを使う（spec 6「キーは `weather:{city}`」。外部呼び出しを増やさない）。質問 4。
- いまの `app/services/weather.py` の `get_weather` は、キャッシュの読み書きと `/weather` の整形が 1 つになっている。「保存値を読む → 新しければ使う → 外部APIを呼ぶ → 失敗したら stale」の流れを、整形の関数を引数に取る形で切り出し、`/weather` と `/cloud-base` の両方から使う。**`/weather` の動きは変えない**（既存のテストをそのまま通す）。
- 4 項目が入る前に保存された値（デプロイの直後、最大 6 時間）は、`/cloud-base` では「使えない保存値」として外部APIを呼び直す（spec 6「形が違う場合は、キャッシュなしとして呼び直す」と同じ扱い）。

### モデルの読み込み

- 起動のとき（`lifespan`）に 1 回だけ `ml.model.load` を呼び、`app.state` に置く。パスはコードの定数（リポジトリの `models/cloud_base.joblib`）。環境変数・利用者の入力からは作らない。
- 読めなければ（`ModelLoadError`）、警告ログを 1 行残して起動は続ける。`/cloud-base` だけが 503 `model_unavailable`、ほかのエンドポイントは動く。質問 2。
- 503 の判定は外部APIを呼ぶ前に行う（モデルがないのに Open-Meteo の枠を使わない）。`city` の検証（422）のほうが先。
- 予測は CPU の計算（1 行）なので、イベントループの上でそのまま呼ぶ。かかる時間は実行して確かめる（下の「確認が必要な項目」）。

### 依存とイメージ

- API が実行時に要るもの：`pandas`（`ml/features.py`）、`lightgbm`、`joblib`。いまは依存グループ `ml` にあり、API のイメージに入っていない。
- 案（質問 7）：この 3 つを `[project].dependencies` に移す。`pyarrow`・`matplotlib` は `ml` に残す。**新しく取得するパッケージはない**（`uv.lock` に入っているものの置き場所が変わるだけ）。
- `Dockerfile`：実行のイメージに `libgomp1` を足す（`Dockerfile.dev` と同じ）、`COPY models ./models` を足す。非 root・slim はそのまま。

## 変更・追加するファイル

| ファイル | 内容 |
|---|---|
| `app/clients/open_meteo.py` | `HOURLY_VARIABLES` に 4 項目を足す（ブロッカー 1 が済んだものだけ） |
| `app/services/forecast_cache.py`（新規。名前は仮） | `app/services/weather.py` から、キャッシュ・stale の流れを切り出す。整形の関数を引数に取る |
| `app/services/weather.py` | 上を使う形に直す。外から見た動きは変えない |
| `app/services/cloud_base.py`（新規） | `hourly` から `valid_at` の行を選んで検証する、1 行の表にする、`features` → `predict_m`・ベースライン → 応答を作る |
| `app/routers/cloud_base.py`（新規） | `GET /cloud-base`。`city` は `City`（省略時 `tokyo`。質問 8）。モデルを `app.state` から受け取る依存 |
| `app/schemas.py` | `CloudBaseResponse`（5 項目） |
| `app/errors.py` | `ModelUnavailableError` と 503 `model_unavailable` のハンドラ。例外の文面・パスは応答に出さない |
| `app/main.py` | `lifespan` でモデルを読む。ルーターを足す |
| `pyproject.toml`・`uv.lock` | 依存の置き場所の変更（質問 7） |
| `Dockerfile` | `libgomp1`、`COPY models`、`--no-group ml` の行のコメント |
| `tests/fixtures/open_meteo/forecast_<city>_cloud_base.json`（新規、2 つ）・`tests/fixtures/README.md` | 4 項目を足した URL で取得した実レスポンス（ブロッカー 2）。既存の 4 つの fixture は変えない（質問 9） |
| `tests/app/test_cloud_base_service.py`・`test_cloud_base_router.py`（新規） | テスト 1〜24 |
| `tests/app/test_open_meteo_client.py` | `EXPECTED_HOURLY` に 4 項目を足す（仕様の変更に合わせる 1 か所） |
| `tests/app/test_weather_*.py` | 変更なしの見込み。切り出しで直す必要が出たら、直す前に理由を報告する |
| `docs/spec.md` | 5（`/cloud-base` の決まり）、7（表の状態）、9（イメージ・`baseline_m`）、14（#12 の状態）。**人間の回答にある内容だけ**。書く前に、回答にない変更を一覧にして聞く |
| `docs/model-card.md` | 8 節の `pressure_msl_hpa` の行を、確認の結果に直す |
| `.github/workflows/ci.yml`、`docker-compose.yml`、`ml/`、`notebooks/`、`models/` | 変更なしの見込み |

### 確認が必要な項目（記憶で確定させない）

| 項目 | 確かめ方 |
|---|---|
| 予報の `hourly` の 4 項目の名前・単位・値の型、`wind_speed_unit=ms` が `hourly` にも効くか、`precipitation` の区切り（前の 1 時間の合計か） | 公式ドキュメントと実レスポンス（ブロッカー 1） |
| `relative_humidity_2m`・`cloud_cover` などが整数で返るか、小数か（検証の型を決める） | 取得した fixture を見る |
| pandas・lightgbm を入れた API のイメージで起動できるか、イメージの大きさ、起動にかかる時間 | `docker build` して実行する。大きさは前後を報告する |
| 1 回の予測にかかる時間（イベントループを止める長さ）、キャッシュヒット時の応答時間（spec 10 の目安 p95 100 ms） | 実行して測る。長ければ報告して、スレッドに逃がすかを聞く |
| 1 行の表を `features` に渡したときの型（`time` の単位、整数の列）で、学習のときと同じ予測になるか | 過去データの fixture の 1 行を、表ごと渡した場合と 1 行だけ渡した場合で、特徴量が一致することをテストで確かめる |
| `TestClient` の `lifespan` でモデルを読む時間が、既存のテスト全体をどれだけ遅くするか | 実行して確かめる |

## テスト一覧（先に書く順）

| # | テスト名 | 種類（正常/異常/境界） | 確かめること |
|---|---|---|---|
| 1 | `test_valid_at_is_latest_hour_at_or_before_now` | 境界 | 13:41 → 13:00、正時ちょうどはその時刻、59 分 59 秒は前の正時 |
| 2 | `test_valid_at_can_be_first_row` | 境界 | 現地の 0 時台（`hourly` の先頭の行）でも選べる |
| 3 | `test_row_before_first_hourly_time_is_upstream_error` | 異常 | 現在が `hourly` の先頭より前なら 502 |
| 4 | `test_input_row_maps_open_meteo_names_to_feature_columns` | 正常 | fixture の行の値が、`ml/archive.py` の `VARIABLES` と同じ対応で入る。`city`・`time`（UTC）が付く |
| 5 | `test_input_row_gives_same_features_as_training_path` | 正常 | 同じ値を、学習の側の表として `features` に渡した結果と一致（学習と推論のずれがない） |
| 6 | `test_missing_or_null_hourly_item_is_upstream_error` | 異常 | 11 項目のそれぞれについて、列がない・その行が null・文字列・真偽値なら 502（パラメータで分ける） |
| 7 | `test_null_in_other_rows_is_ignored` | 境界 | 使わない行（先の時刻）が null でも 200 |
| 8 | `test_hourly_columns_of_different_length_is_upstream_error` | 異常 | 列の長さが `time` と違えば 502 |
| 9 | `test_predicted_m_comes_from_model_with_feature_columns_in_order` | 正常 | 代わりのモデル（渡された表を記録して決まった値を返す）で、列が `FEATURE_NAMES` の順、1 行、値が fixture のもの |
| 10 | `test_predicted_m_matches_committed_model` | 正常 | リポジトリのモデルで、`ml.model.predict_m` を直接呼んだ値と一致（何 m かの期待値は作らない） |
| 11 | `test_predicted_m_is_within_zero_and_cap` | 境界 | 範囲外を返す代わりのモデルでも、応答は 0〜1,524 |
| 12 | `test_baseline_m_follows_rule_of_thumb` | 正常 | fixture の気温・露点から spec の式で出した値（質問 3 の範囲・丸めの決まりどおり） |
| 13 | `test_baseline_m_boundaries` | 境界 | 露点が気温より高い行、上限を超える行（fixture の値を書き換えた応答で。質問 3 の決まりどおり） |
| 14 | `test_cloud_base_returns_spec_keys_and_types` | 正常 | 200、キーは spec の 5 つだけ、`valid_at` は UTC の `Z`、`model_version` はモデルのファイルの値 |
| 15 | `test_cloud_base_for_each_city` | 正常 | 東京・ベルリンで、`city` と、その都市の緯度・経度で外部APIを呼ぶこと。`city_code` が都市で違う |
| 16 | `test_cloud_base_city_default_and_invalid` | 異常 | 省略は `tokyo`（質問 8）、許可リスト外・空文字は 422 `invalid_city`、外部APIを呼ばない |
| 17 | `test_model_unavailable_returns_503` | 異常 | モデルが読めていないとき 503 `model_unavailable`。応答にパス・例外の文面がない。外部APIを呼ばない |
| 18 | `test_app_starts_without_model_and_other_endpoints_work` | 異常 | モデルのファイルがない・壊れている状態で起動でき、`/health`・`/weather`・`/daylight` は 200、警告ログにパスの中身が出ない |
| 19 | `test_invalid_city_wins_over_model_unavailable` | 境界 | モデルなし ＋ 不正な `city` は 422 |
| 20 | `test_cloud_base_upstream_failure_without_cache_is_502` | 異常 | タイムアウト・5xx（リトライ後）・4xx・JSON でない応答で 502 `upstream_error` |
| 21 | `test_cloud_base_uses_weather_cache` | 正常 | `/weather` の後、TTL 内の `/cloud-base` は外部APIを呼ばない。逆の順でも同じ |
| 22 | `test_cloud_base_refetches_when_cached_entry_lacks_new_items` | 境界 | 4 項目のない保存値（既存の fixture の形）があるときは、外部APIを呼び直して 200 |
| 23 | `test_cloud_base_uses_stale_cache_when_upstream_fails` | 境界 | TTL を過ぎて上限内の保存値 ＋ 外部APIの失敗 → 200（`valid_at` はいまの時刻で選び直す）。上限を過ぎたら 502（質問 4 の決まりどおり） |
| 24 | `test_openapi_documents_cloud_base_errors` | 正常 | `/openapi.json` に 422・502・503 が載る |
| 25 | `test_client_requests_hourly_and_daily_params`（既存を直す） | 正常 | 外部APIに送る `hourly` に 4 項目が入っている |
| 26 | 既存の `tests/app/test_weather_*.py`（変更なし） | 正常 | 切り出しの後も、`/weather` のキャッシュ・stale・502 のテストがそのまま通る |

- 期待値は、fixture の値、spec の式・上限、`ml/` の関数を直接呼んだ値、代わりのモデルが返す決まった値だけ。**予測が何 m になるかをテストに書かない**。
- モデルのパスは定数なので、「読めない」場合のテストは、依存の差し替えと、`lifespan` が読む定数を一時的な場所に向けることで作る（環境変数は足さない）。
- Red の確認：サービス（1〜13）→ ルーター（14〜24）→ クライアント（25）の順。骨組みで失敗することを実行して確かめ、骨組みでも通るテストは一覧にする。Green の後、実装をわざと壊してテストが失敗することを確かめる（#8〜#11 と同じ）。
- 切り出し（`forecast_cache`）は、Green の後の Refactor ではなく先に行う：既存のテストが通ったまま切り出す → その上に `/cloud-base` を足す。

## 追加する依存パッケージ

新しく取得するものは **なし**。置き場所だけ変える（質問 7）。

| パッケージ | 理由 | 代替案 |
|---|---|---|
| `pandas`・`lightgbm`・`joblib`（`ml` グループ → `[project].dependencies`） | API が実行時に `ml/features.py`・`ml/model.py` を使う | (b) 新しい依存グループ（`inference` など）を作り、`Dockerfile` でそのグループを入れる。(c) `Dockerfile` で `ml` グループごと入れる（`pyarrow`・`matplotlib` も入り、イメージが大きくなる） |

- `Dockerfile` に Debian のパッケージ `libgomp1`（`Dockerfile.dev` で導入済みのものと同じ）。
- 一緒に入るもの：`numpy`・`scipy`・`narwhals`（どれも `uv.lock` に入っている）。イメージの大きさは実行して報告する。

## セキュリティ上の注意

- 入力検証：`city` は許可リスト（`City`）。ほかのパラメータは受け取らない。外部APIの値は、使う行を厳密に検証する（数値の文字列・真偽値・null を受け付けない）。
- シークレット：使わない。`.env` は読まない。新しい環境変数は足さない。
- モデルのファイル（pickle 形式）：読み込むのは、イメージに入れたリポジトリの `models/cloud_base.joblib` だけ。パスは定数。503 の応答とログに、パス・例外の文面を出さない。イメージの中では非 root の利用者が読むだけ（書き込めない場所に置く）。
- 外部通信（ホスト・タイムアウト）：`api.open-meteo.com` だけ（既存のクライアント。接続 3 秒・全体 10 秒・リトライ 2 回）。通信先を増やさない。URL は利用者の入力から作らない。
- 作業のために取得するもの：fixture の取得で Open-Meteo を 2 回（ブロッカー 2）、手動確認で 2 回。`docker build` で PyPI と Debian から、上に書いたパッケージ。これ以外が要る場合は、取得する前に伝える。

## リスク・未決事項

1. **`pressure_msl` などが予報の `hourly` で取れない・意味が違う場合**、#12 は止まる（特徴量を外して学習し直すのは #11 の決まり「テストの年を見た後はモデルを変えない」とぶつかるので、そのときは進め方を聞く）。
2. **成功基準に届いていないモデルを公開する**。低いシーリングの高さは概算式より良くない（`docs/model-card.md` 7 節）。応答には `baseline_m` と `model_version` が並ぶだけで、それは伝わらない（質問 6）。
3. **`predicted_m: 1524` は「1,524 m より下にシーリングがない」の意味**だが、応答からは分からない（質問 5）。
4. **学習は再解析、推論は予報**。さらに `valid_at` は現在以前の正時なので、最大 59 分前の時刻の値で「いま」を答える。差は測らない。
5. **stale のとき、応答から古さが分からない**（`fetched_at`・`stale` が spec の応答にない。質問 4）。
6. **`app` を import すると pandas が読み込まれるようになる**。この PC では numpy を import できないので、`tests/app/` も手元の `uv run pytest` では動かなくなり、すべて `Dockerfile.dev` の中で実行することになる（いまは `tests/ml/` だけ）。回避はしない。
7. **`/weather` のキャッシュのコードを切り出す**（#5・#6 の部分）。動きを変えないことは既存のテストで守るが、差分は大きくなる。
8. **API のイメージが大きくなる**（pandas・numpy・scipy・lightgbm）。CI の `docker build` の時間も延びる。
9. **Issue #23 の本文を読めていない**（`gh` がこの環境にない）。spec の機能 #12 と同じ内容という前提。
10. 予測は同期の計算。同時に多く来ると、その間ほかのリクエストが待つ（測って報告する）。

## 実行のたびに枠を使うものの見積もり

- Open-Meteo：fixture の取得 2 回、ブロッカー 1 の照合で数回、手動確認 2 回。テスト・CI では 0 回。
- GitHub Actions：PR の作成で 1 回、レビュー後の修正と dev-log で 1〜2 回。

## ブロッカー（人間の対応が必要なこと）

1. **予報の `hourly` の項目の確認**（spec 7 の表）。公式ドキュメント（open-meteo.com の Forecast API）で次を確かめ、表の状態を更新する必要があります。これまでどおり「AI が公式ドキュメントと実レスポンスを照合する」でよければ、その指示をください。
   - `hourly=` で `dew_point_2m`・`relative_humidity_2m`・`pressure_msl`・`wind_speed_10m` が取れること、単位（℃・%・hPa・`wind_speed_unit=ms` で m/s）
   - `hourly` の `precipitation` が「前の 1 時間の合計」、ほかが「その時刻の値」であること（過去データと同じ意味か）
2. **fixture の取得の許可**：4 項目を足した URL で、東京・ベルリンを 1 回ずつ `curl` で取得して保存する（ブロッカー 1 の後）。
3. **依存の置き場所の変更と `libgomp1` の承認**（質問 7）。
4. **Issue #23 の本文**：spec の機能 #12 にない要件があれば教えてください。

2026-10-13 の承認時の扱い（回答は「推奨で進めてください」）：

- 1 は、「AI が公式ドキュメントと実レスポンスを照合する」の指示として扱う。実装の最初に行い、呼ぶ URL と回数を先に伝える。結果を報告し、spec 7 の表を更新してから、4 項目を使うコードに進む。取れない・意味が違う項目があれば、そこで止まって聞く（リスク 1）。
- 2・3 は、計画の承認に含まれるものとして扱う（fixture を取得する前、依存を動かす前に、内容をもう一度伝える）。
- 4 は、追加の要件の連絡がなかったので、spec と同じ内容として進める。

## 質問

それぞれ推奨を 1 つ書いています。「推奨で」と返してもらえれば、その内容で進めます。

**回答（2026-10-13）：「推奨で進めてください」。1〜10 はすべて推奨の内容で進める。**

1. **`valid_at`（どの時刻を予測するか）**：推奨は **現在以前の最も近い正時**（13:41 → 13:00）。「いまの雲底」にいちばん近く、行がいつもある。ほかの案：(b) 最も近い正時（13:41 → 14:00。学習のときの「前後 30 分の METAR」に近い）、(c) `/weather` の `hourly` の先頭と同じ「次の正時」。
2. **モデルが読めないときの起動**：推奨は **起動は続け、`/cloud-base` だけ 503**（spec の 503 のとおり。天気と日照は使える）。読み込みは起動のときの 1 回だけで、後から読み直さない。ほかの案：起動を失敗させる（CD のスモークテストで気づきやすいが、503 を返す場面がなくなる）。
3. **`baseline_m` と丸め**：推奨は **`baseline_m` も 0〜1,524 m に収める**（`ml/baseline.py` の `baseline_m`。`predicted_m` と同じ範囲で比べられる。収めないと、露点差が大きい日に 3,000 m などになり、上限のある `predicted_m` と並べて読めない）。**2 つとも整数に四捨五入**（spec の例が整数）。ほかの案：`baseline_m` は式のまま（負だけ 0 にする）／小数 1 桁。
4. **キャッシュと stale**：推奨は **`/weather` と同じ保存値・同じ決まりを使い、外部APIが失敗したら上限 6 時間までの保存値で予測を返す**（`valid_at` はいまの時刻で選ぶので、古い予報のその時刻の値を使うことになる）。応答に `stale` は足さない。ほかの案：`/cloud-base` は stale を使わず 502。
5. **`predicted_m` が上限（1,524）のとき**：推奨は **そのまま 1524 を返し、意味は spec と OpenAPI の説明に書く**（項目は足さない。CLAUDE.md「spec にない仕様を足さない」）。ほかの案：`cap_m: 1524` を応答に足す（spec の変更になる）。
6. **成功基準に届いていないモデルの出し方**（#11 からの申し送り）：推奨は **そのまま出す**。`model_version` と `baseline_m` を並べて返し、限界は spec 5 と `docs/model-card.md` に書く。応答に注意書きの項目は足さない。
7. **依存の置き場所**：推奨は **`pandas`・`lightgbm`・`joblib` を `[project].dependencies` に移す**（API が実行時に使うものは、プロジェクトの依存にするのが素直。`pyarrow`・`matplotlib` は `ml` のまま）。ほかの案は「追加する依存パッケージ」の (b)(c)。
8. **`city` の省略**：推奨は **`tokyo`**（`/weather`・`/daylight` と同じ）。空文字は 422。
9. **fixture**：推奨は **既存の 4 つは変えず、`forecast_<city>_cloud_base.json` を 2 つ足す**（既存のテストは取得時刻に合わせた期待値が多く、取り直すと広く影響する。既存の fixture は「4 項目が入る前の保存値」のテストにも使える）。ほかの案：4 つとも取り直して `FIXED_NOW` を変える。
10. **分割**：推奨は **分けない**（1 つの PR）。分ける場合は「キャッシュの流れの切り出し（動きを変えない）」を先の PR にする案がありますが、それだけでは機能にならないので一緒にします。

## 実装時の変更

（2026-10-13）

- **ブロッカー 1 の結果**：4 項目とも予報の `hourly` で取れ、単位・意味は過去データと同じだった（公式ドキュメントの表：`precipitation` は Preceding hour sum、ほかは Instant。実レスポンス：`°C`・`%`・`hPa`・`m/s`、168 行で null なし）。`current` は公式に「15-minutely weather model data」で、実レスポンスの `current.time` も 15 分刻みだった。特徴量は外していない。学習のやり直しもしていない。
  - 外部通信：公式ドキュメントの読み取り 1 回、Open-Meteo 2 回（そのまま fixture にした）、手動確認で 2 回（東京・ベルリンの `/cloud-base` の最初の 1 回ずつ。その後のリクエストと `/weather` は保存値を使った）。
- **キャッシュの流れを、新しいファイルに切り出さなかった**（計画では `app/services/forecast_cache.py`）。既存のテストが、警告ログの出どころを `app.services.weather` と確かめていて、切り出すとその期待値を変えることになるため。`app/services/weather.py` の中で、整形の関数を引数に取る `get_forecast` にし、`get_weather` と `/cloud-base` がそれを使う。既存の `/weather` のテストは 1 行も変えていない。
- **検証する項目は 10 個**（計画のテスト 6 は「11 項目」）。特徴量に使うのは 10 個で、`weather_code` は使わない。型は 10 個とも小数として検証する（整数で届いても受け付け、文字列・真偽値・null は 502）。
- **テストの数が計画（26 項目）より多い**（パラメータで分かれた場合を数えて 156 件）。足した場合：`hourly` の最後の行より後の時刻、`hourly` そのものが壊れている応答、小数の UNIX 秒、16 日ぶんを超える行数、四捨五入（0.5 は切り上げ）、キャッシュから返すときに行を選び直すこと、4 項目のない保存値と外部APIの失敗が重なったときの 502、予測に使えない応答を保存しないこと、モデルを起動のときに 1 回だけ読むこと。弱めたテスト・skip したテストはない。
- **テスト用の補助ファイル `tests/app/cloud_base_fakes.py` を足した**（計画のファイル一覧にない）。モデルの代わり（渡された表を記録する）と、fixture から期待値を読む関数。
- **既存のテストで変えたのは 1 か所**：`tests/app/test_open_meteo_client.py` の `EXPECTED_HOURLY`（外部APIに送る項目。計画どおり）。`tests/conftest.py` には、fixture の読み込みと時刻の定数を足しただけ。
- **503 の判定をエンドポイントの中に置いた**（依存の中で例外を出すと、不正な `city` より先に 503 になるため）。順は 422 → 503 → 外部API。
- **起動のときの警告ログ**：`cloud base model could not be loaded; /cloud-base will return 503` の 1 行。パス・例外の文面は出さない。
- **依存**：`pandas`・`lightgbm`・`joblib` を `[project].dependencies` に移した。`uv.lock` は 114 パッケージのままで、バージョンの変更はない（置き場所の 6 行だけ）。`pip-audit` は問題なし。
- **API のイメージ**：219 MB → 629 MB。`libgomp1` と `COPY models` を足した。起動して `/health` が返るまで約 4 秒（計り方は 1 秒おきの確認なので目安）。非 root（uid 10001）のまま。
- **応答時間（手元、1 回ずつ）**：キャッシュに当たらない最初の 1 回が 0.23 秒（東京）・0.07 秒（ベルリン）、キャッシュに当たる 3 回が 0.022〜0.024 秒（`curl` の時間。spec 10 の目安は p95 100 ms）。予測はイベントループの上でそのまま呼んでいる。
- **手動確認（2026-10-13T14:27Z、API のイメージ）**：東京 `predicted_m: 1524`・`baseline_m: 212`、ベルリン `predicted_m: 1524`・`baseline_m: 1088`（どちらも `valid_at` は 14:00Z）。モデルのフォルダを空にして起動すると、`/cloud-base` は 503 `model_unavailable`、`/health`・`/daylight` は 200。
- **実装をわざと壊す確認**：17 通り（正時に切り捨てない、偶数への丸め、気温と露点の取り違え、列の長さを見ない、厳密な検証をやめる、キャッシュから返すときに行を選び直さない、都市を固定する、ログにパスを出す、読み込みの失敗を受けない、行数の上限を見ない、時刻の型を見ない、`pressure_msl` を要求しない、503 を 500 にする、モデルの判定を外部APIの後にする、リクエストのたびにモデルを読む、stale の上限を見ない、壊れた応答を保存する）。最初は「行数の上限」「時刻の型」の 2 つが検出されなかったので、テストを 2 つ足した。足した後は 17 通りすべてでテストが失敗した。
- **spec に書く前の確認**：質問の回答に文としてないもの 6 つ（入力は `hourly` の 1 行、欠けた値では予測しない、判定の順、4 項目のない保存値の扱い、丸め、イメージ）を一覧にして聞いた。返事は `/review` の後の「推奨で進めてください」で、レビューの修正案（「6 つを追記する」）のとおりに書いた。
- **この PC の手元の `uv run pytest`**：`app` が pandas を読み込むようになったので、`tests/app/` も `Dockerfile.dev` の中でしか動かない（リスク 6 のとおり。確認はすべてイメージの中で行った）。

### レビュー後の修正（2026-10-13）

回答は「推奨で進めてください」。レビューの修正案のとおりに直した（🔴 2 つ、🟡 のうち単位の確認と Redis のテスト）。

- `app/services/cloud_base.py`：**NaN・無限大を 502 にした**（`allow_inf_nan=False`）。直す前は、`pressure_msl` が NaN だと欠損のまま予測して 200、`temperature_2m` が NaN だと 500 になった（実行して確かめた）。テスト 30 件を先に足し、失敗を確かめてから直した。
- `app/services/cloud_base.py`：**`hourly_units` を、学習のときの単位（`ml/archive.py` の `VARIABLES`）と突き合わせる**。違う・ない場合は 502。時刻の単位（`unixtime`）も見る。テスト 25 件を先に足した。
- `tests/app/test_cloud_base_router.py`：保存先を Redis（fakeredis）に替えても `/weather` と保存値を共用するテストを 2 件足した（直す前から通る、動きの確認）。
- `docs/spec.md`：5 に `/cloud-base` の決まり、9 に依存とイメージ、14 の #12 を完了に。
- テストは 1,209 件（`/cloud-base` のぶんは 213 件）、カバレッジ 99.46%。
- 直していないもの：
  - **spec 7 の「前の 1 時間の合計／その時刻の値」**は、公式ドキュメントを WebFetch の要約で読んだもの。人間が `open-meteo.com/en/docs` の「Hourly Parameter Definition」の表を一度見て確かめる必要がある。
  - **`docker compose up --build`（実物の Redis）での手動確認**はしていない（`docker run`・メモリキャッシュで確かめた。Redis は fakeredis のテスト）。
  - **#14（CD）への申し送り**：スモークテストで、`/cloud-base` が 503 でないこと（モデルと `libgomp1` がイメージに入っていること）を確かめる。CI はイメージを作るだけで起動しない。
  - 🟢 の指摘（名前の対応表の置き場所、テストの書き方、`libgomp1` のバージョン）は別の Issue の候補。
