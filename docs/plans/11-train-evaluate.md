# 計画：#11 学習・評価（Issue #21）

状態：承認済み（2026-10-13。質問 1〜9 はすべて推奨のとおり）

## 目的と受け入れ条件

spec.md「14. 機能一覧」より：

> | 11 | 学習・評価 | `04`・`05` 完了、ベースラインとの比較を `docs/model-card.md` に記録 |

spec.md「9. 雲底高度予測（ML）」より：

> | `04_train.ipynb` | 学習 | `models/cloud_base.joblib` |
> | `05_evaluate.ipynb` | テスト評価、都市別・季節別 | `reports/metrics.json`、`docs/model-card.md` |
>
> - 特徴量（候補）：気温、露点、気温と露点の差、相対湿度、海面気圧、風速、層別雲量、時刻・季節（周期表現）、太陽高度（`app/services/solar.py` の計算を共有）、都市。
> - 時系列分割：学習 2018〜2023（6 年）、検証 2024、テスト 2025。ランダム分割はしない。
> - #11 で 1 回だけ、学習を 2021〜2023（3 年）にした場合と、検証の年（2024）の MAE で比べる。3 年のほうが良ければ替える。テストの年はこの比較に使わない。結果は `docs/model-card.md` に書く。
> - テストの年（2025）のベースラインは、#11 の `05_evaluate` で同じ関数を使って出す。
> - 成功基準：テストの年（2025）で、都市ごとに、(1) 全体の MAE が「いつも上限」より 10% 以上小さい、(2) 上限より下の行だけの MAE が概算式より 10% 以上小さい、の両方。
> - 予測時点より後の情報を特徴量に使わない。学習は過去データ、推論は予報データを使うため、その差の影響を `docs/model-card.md` に記録する。特徴量作成は `ml/features.py` のみに実装する。

#10 からの申し送り：

- テストの年のベースライン（3 つの予測）を、`05_evaluate` で同じ関数から出す。
- 新しい特徴量は `ml/features.py` に足す。
- **成功基準に届かなかったときの扱いを、計画で決める**（質問 1）。

完了の確認方法：

1. `Dockerfile.dev` のイメージの中で `uv run --locked pytest --cov=app --cov=ml` が通る（カバレッジ 80% 以上）
2. 同じく `ruff check .`・`ruff format --check .`・`mypy app ml`・`pip-audit` が通る（依存を足すので `pip-audit` も実行する）
3. `pytest --nbmake notebooks/` が、サンプルデータで、外部と通信せずに通る（01〜05）
4. 全期間のデータで `04_train` を実行し（`--network none`）、`models/cloud_base.joblib` と `reports/training.json` ができる。もう一度実行して、`reports/training.json` が同じ内容になる
5. 全期間のデータで `05_evaluate` を実行し、`reports/metrics.json` に、テストの年の都市別・都市 × 季節別の指標（モデルと 3 つのベースライン）と、成功基準の判定が入っている
6. `docs/model-card.md` に、ベースラインとの比較・成功基準の判定・6 年と 3 年の比較・学習と推論の入力の差が書いてある。**数値はすべて `reports/` の JSON にある値**（スクリプトで突き合わせる）
7. spec 9 に今回決めたことを追記し、機能一覧 #11 を完了にする
8. PR で CI が通る

## 今回やらないこと

- `/cloud-base`、モデルの読み込みを API に組み込むこと、API のイメージ（`Dockerfile`）の変更 → #12
- Open-Meteo の予報で `pressure_msl` などが取れるかの確認 → #12（spec 7 の表に「#12 で確認する」とある。リスク 3）
- ハイパーパラメータの探索、モデルの種類の比較、都市ごとに別のモデル（質問 4）
- 過去の時刻の値を使う特徴量（1 時間前との差など）。使うのは、その正時の Open-Meteo の値だけ
- 学習と推論の入力の差を、数値で測ること（過去の予報のデータが要る。spec 7 で未確認。質問 8）
- テストの年の結果を見た後の、モデル・特徴量・成功基準の変更（質問 1）
- データの取り直し、parquet の作り直し、`reports/baseline.json` の変更（外部APIは呼ばない）
- `02_eda.ipynb`・`03_baseline.ipynb` の変更

## 変更・追加するファイル

| ファイル | 内容 |
|---|---|
| `ml/features.py` | `FEATURE_NAMES`（列の名前と順）と `features(observations)`（特徴量の表を返す）を足す。中身は下の「特徴量」。既存の 3 つの関数は変えない |
| `ml/split.py` | 比較用の学習期間 `TRAIN_YEARS_SHORT = (2021, 2022, 2023)` と、年の一覧で行を選ぶ関数を足す。`SPLIT_YEARS` は変えない |
| `ml/train.py`（新規） | `PARAMS`・`SEED`（定数）、`fit(train_features, train_target, validation_features, validation_target)`：正解のある行だけで LightGBM を学習し、検証の年で打ち切りの回数を決める。学習の設定だけを持つ |
| `ml/model.py`（新規） | 保存するひとまとまり（モデル・`FEATURE_NAMES`・`model_version`・上限・学習の年）、`save`・`load`、`predict_m(model, features)`：予測を 0〜1,524 m に収める。列の名前・順が合わなければ `ValueError`。#12 の API が使う側 |
| `ml/evaluate.py` | `success_criteria(...)`：都市ごとに、成功基準の 2 つの改善率と、満たしたかどうかを返す（下の「成功基準の判定」）。既存の関数は変えない |
| `notebooks/04_train.ipynb`（新規） | 下の「ノートブックの構成」。出力を消してコミット |
| `notebooks/05_evaluate.ipynb`（新規） | 同上 |
| `models/cloud_base.joblib`（新規） | 全期間で学習したモデル。git に入れる（質問 6） |
| `reports/training.json`（新規） | 04 の結果：特徴量の一覧、学習の設定、打ち切りの回数、検証の年の指標、6 年と 3 年の比較、どちらを採ったか、特徴量の重要度。**spec の成果物の表にない追加**（質問 7） |
| `reports/metrics.json`（新規） | 05 の結果：テストの年（と参考に検証の年）の、モデルと 3 つのベースラインの指標（全体・都市別・都市 × 季節別）、成功基準の判定、`model_version` |
| `docs/model-card.md`（新規） | 下の「model-card の構成」。数値は `reports/` から写す |
| `tests/ml/test_features.py`・`test_split.py`・`test_evaluate.py` | 追加（テスト 1〜12、25〜29） |
| `tests/ml/test_train.py`・`test_model.py`（新規） | テスト 13〜24 |
| `tests/test_notebooks.py` | 04・05 があること、`reports/training.json`・`reports/metrics.json` の形、モデルのファイルがあること（テスト 30〜34） |
| `pyproject.toml`・`uv.lock` | 依存グループ `ml` に `lightgbm`・`joblib`（下の「追加する依存パッケージ」）。型の情報がなければ mypy の設定を足す |
| `Dockerfile.dev` | LightGBM が要る共有ライブラリ（`libgomp1`）が `python:3.14-slim` になければ、`apt-get` で足す（実行して確かめる） |
| `docs/spec.md` | 9 に、特徴量の一覧、学習の設定、6 年と 3 年の比較の結果、成果物の表（`reports/training.json`）、テストの年の結果、機能一覧 #11 の状態。**人間の回答にある内容だけ**。書く前に、回答にない変更を一覧にして聞く |
| `.github/workflows/ci.yml`、`Dockerfile`、`tests/fixtures/` | 変更なしの見込み |

### 特徴量（`ml/features.py` の `features`）

入力は `city`・`time`（UTC）と Open-Meteo の列だけ。**METAR の列（視程、METAR の気温・露点、雲の層）は使わない**（推論のときにない。正解のもとでもある）。

| 列 | 作り方 | spec の候補 |
|---|---|---|
| `temperature_c`、`dew_point_c`、`relative_humidity`、`pressure_msl_hpa`、`wind_speed_ms` | そのまま | 気温、露点、相対湿度、海面気圧、風速 |
| `dew_point_spread_c` | 既存の関数 | 気温と露点の差 |
| `cloud_cover`、`cloud_cover_low`・`_mid`・`_high` | そのまま | 層別雲量 |
| `local_hour_sin`・`local_hour_cos` | 現地の時（既存の `local_hour`）を 24 で 1 周する sin・cos | 時刻（周期表現） |
| `day_of_year_sin`・`day_of_year_cos` | 現地の日付の「年の何日目」を 365.25 で 1 周する sin・cos | 季節（周期表現） |
| `solar_elevation_deg` | `app/services/solar.py` の `solar_elevation_deg(緯度, 経度, 時刻)`。緯度・経度は `app/cities.py` | 太陽高度 |
| `city_code` | 都市を整数にしたもの（`City` の定義の順。東京 0、ベルリン 1） | 都市 |
| `precipitation_mm` | そのまま。**spec の候補にない**（質問 3） | — |

- 欠損はそのまま渡す（LightGBM は欠損を扱える。学習データの気象の列に欠損はない：`docs/eda.md` 1 節）。
- 知らない都市・UTC でない時刻・列の不足は `ValueError`。渡した表は書き換えない。

### 学習（`ml/train.py`）

- モデルは LightGBM の回帰 1 つ（2 都市で共通。都市は特徴量）。scikit-learn は使わず、LightGBM の `train` を直接使う（依存を増やさないため）。
- 目的関数は MAE（指標と同じ。質問 4）。設定は定数で固定し、探索しない。乱数シードは固定、スレッドは 1 つ（再実行で同じ結果にするため）。
- 学習に使うのは、学習の年の、`target_m` が欠損でない行。検証の年（2024）の MAE が良くならなくなったら打ち切り、そのときの回数を採る。
- 予測は 0〜1,524 m に収める（ベースラインと同じ範囲）。
- **学習の年で学習したものをそのまま最終のモデルにする**（検証の年を足して学習し直さない。spec の分割のまま）。

### 6 年と 3 年の比較（04 の中で 1 回）

- 同じ特徴量・同じ設定・同じ打ち切りの決まりで、学習 2018〜2023 と 2021〜2023 の 2 つを作り、検証の年（2024）で比べる。
- **比べる数値は、検証の年の全体（2 都市を合わせた）の MAE 1 つ**。3 年のほうが小さければ 3 年、同じか大きければ 6 年（質問 5）。都市別の MAE と、上限より下の行の MAE は、参考として並べる（判定には使わない）。
- テストの年の行は、04 では読み込んだ直後に落とす（表にも出さない）。

### 成功基準の判定（`ml/evaluate.py` の `success_criteria`）

- 入力は、ある都市の、モデル・「いつも上限」・概算式の 3 つの指標（`evaluate` の戻り値）。
- 出すもの：(1) 全体の MAE の改善率（いつも上限に対して）、(2) 上限より下の行の MAE の改善率（概算式に対して）、それぞれが 10% 以上か、両方満たしたか。
- 判定は丸める前の値で行う。ちょうど 10% は満たす（spec「10% 以上」）。比べる相手の MAE が 0・欠損のときは判定しない（`None`）。

### ノートブックの構成

| | 節 | 内容 |
|---|---|---|
| 04 | 0. 設定・読み込み | 03 と同じ `DATA_FETCH_MODE`（既定 `sample`）。`full` は parquet を読み、テストの年を落とす |
| | 1. 特徴量と目的変数 | `features`・`target_m`・`split`。学習・検証の行数（都市別） |
| | 2. 学習（6 年）と検証 | `fit` → 検証の年の指標（モデルと 3 つのベースライン、都市別） |
| | 3. 学習（3 年）との比較 | 上の決まりで比べ、採るほうを決める |
| | 4. 保存 | `models/cloud_base.joblib` と `reports/training.json`。読み直して同じ予測になることを確かめる |
| 05 | 0. 設定・読み込み | `full` は `models/cloud_base.joblib` を読む |
| | 1. 予測 | テストの年（と検証の年）の、モデルと 3 つのベースラインの予測 |
| | 2. 評価 | `evaluate.report`：全体・都市別・都市 × 季節別 |
| | 3. 成功基準 | `success_criteria`：都市ごとの判定 |
| | 4. 保存 | `reports/metrics.json` |

- **`sample`（2025-01 の 2 日ぶん、約 90 行）**：分割で絞らず、同じ行で学習と評価をする（「落ちないこと」だけを確かめる。数値に意味はない）。一時的な場所に書く。05 は、04 の出力を読まずに、その場で小さく学習する（nbmake はノートブックを別々に実行するので、04 が一時的な場所に書いたファイルを 05 から探さない）。
- JSON には、実行時刻・手元のパスを入れない。数値は小数 2 桁（`evaluate.report` と同じ）。

### model-card の構成

1. 概要（何を予測するか、`model_version`、使いみち、使えない場面）
2. データ（期間、出典と利用条件、除いた行と件数、観測のしかたの変化）
3. 目的変数（上限 1,524 m、`NCD`・`VV` の扱い）
4. 特徴量、学習の設定
5. 分割、6 年と 3 年の比較の結果
6. 結果：検証の年・テストの年。都市別・季節別。3 つのベースラインとの比較
7. 成功基準の判定（満たした・満たさなかったを、都市ごと・基準ごとに）
8. 学習と推論の入力の差（質問 8）、そのほかの限界（`docs/eda.md`「決定の弱いところ」）
9. 再現のしかた

### 確認が必要な項目（記憶で確定させない）

| 項目 | 確かめ方 |
|---|---|
| `lightgbm`・`joblib` が Python 3.14 に入るか、入るバージョン | `uv add` を実行して確かめる。入らなければ止まって報告 |
| `python:3.14-slim` で LightGBM を import できるか（`libgomp1`） | イメージを作って import する |
| LightGBM の設定の名前（目的関数、シード、スレッド数、打ち切り）、欠損の扱い、再実行で同じ予測になるか | 実行して確かめる（知らない名前の警告が出ないこと、2 回の学習で予測が一致すること） |
| `lightgbm`・`joblib` に型の情報があるか（mypy strict） | `mypy` を実行する。なければ、その 2 つだけ `ignore_missing_imports` にする |
| 約 90 行のサンプルで学習が落ちないか | 実行して確かめる |
| モデルのファイルの大きさ、再実行でバイト列が同じになるか | 実行して確かめる（同じにならなければ、同じことを確かめる対象は `reports/training.json` と予測にする） |
| 14 万行ぶんの太陽高度の計算にかかる時間 | 実行して確かめる（遅ければ報告。式は書き写さない） |
| 「ちょうど 10%」の判定が、浮動小数の誤差でずれないか | 実行して確かめる |

## テスト一覧（先に書く順）

| # | テスト名 | 種類（正常/異常/境界） | 確かめること |
|---|---|---|---|
| 1 | `test_features_have_fixed_names_and_order` | 正常 | 列が `FEATURE_NAMES` のとおりで、行の番号を保つ |
| 2 | `test_features_pass_weather_columns_through` | 正常 | 気象の列はそのまま、露点差は既存の関数と同じ |
| 3 | `test_local_hour_is_cyclic` | 正常/境界 | 現地の 0・6・12・18 時で (sin, cos) が (0,1)・(1,0)・(0,−1)・(−1,0)。23 時と 0 時が隣り合う |
| 4 | `test_day_of_year_is_cyclic_and_uses_local_date` | 境界 | 現地の日付で数える（東京の UTC 15:00 は翌日）。12/31 と 1/1 が隣り合う。値は −1〜1 |
| 5 | `test_solar_elevation_matches_solar_module` | 正常 | fixture の行で、`app/services/solar.py` を直接呼んだ値と同じ。都市の緯度・経度を使っている（都市を入れ替えると値が変わる） |
| 6 | `test_solar_elevation_is_positive_at_local_noon_and_negative_at_midnight` | 正常 | 向きの確認だけ（値の期待値は作らない） |
| 7 | `test_city_code_follows_city_order` | 正常 | 東京と ベルリンで違う整数。`City` の順 |
| 8 | `test_features_do_not_need_metar_columns` | 異常 | METAR の列を落とした表でも同じ結果（METAR の値が入りこまない） |
| 9 | `test_features_ignore_other_rows` | 異常 | 後の時刻の行を足しても・行の順を変えても、各行の値が変わらない（その行の値だけで決まる） |
| 10 | `test_features_reject_bad_input` | 異常 | 知らない都市、UTC でない時刻、列の不足は `ValueError` |
| 11 | `test_features_do_not_modify_input` | 異常 | 渡した表を書き換えない |
| 12 | `test_rows_in_years_selects_only_those_years` | 境界 | 2020-12-31T23:00Z は 3 年の学習に入らず、2021-01-01T00:00Z は入る。2024・2025 は入らない |
| 13 | `test_fit_uses_only_rows_with_target` | 境界 | 正解が欠損の行を足しても、同じモデルになる（予測が一致） |
| 14 | `test_fit_is_reproducible` | 正常 | 同じ入力で 2 回学習して、予測が一致 |
| 15 | `test_fit_learns_an_obvious_relation` | 正常 | 手で作った「特徴量が大きいと正解が上限、小さいと低い」表で、予測の大小がその向きになる（値の期待値は作らない） |
| 16 | `test_fit_rejects_empty_or_misaligned_input` | 異常 | 正解のある行が 0、行のずれ、列の違いは `ValueError` |
| 17 | `test_fit_does_not_modify_input` | 異常 | 渡した表を書き換えない |
| 18 | `test_predict_is_within_zero_and_cap` | 境界 | 予測が 0〜1,524 に収まる（外れた値を返すモデルの代わりを渡して確かめる） |
| 19 | `test_predict_keeps_index_and_name` | 正常 | 行の番号を保つ |
| 20 | `test_predict_rejects_wrong_feature_columns` | 異常 | 列の不足・余分・順の違いは `ValueError` |
| 21 | `test_save_and_load_give_same_predictions` | 正常 | 保存して読み直したモデルで、予測が一致。`model_version`・特徴量の一覧・上限が入っている |
| 22 | `test_load_rejects_missing_file` | 異常 | ファイルがなければ決まった例外（#12 の 503 のもと） |
| 23 | `test_load_rejects_unexpected_content` | 異常 | 中身が期待した形でない・特徴量の一覧がいまのコードと違う場合は例外 |
| 24 | `test_model_version_has_expected_form` | 正常 | spec 5 の例（`<日付>-lgbm-v<番号>`）の形 |
| 25 | `test_success_criteria_passes_when_both_are_met` | 正常 | 手で書いた指標（100 に対して 80 など）で、2 つの改善率と判定 |
| 26 | `test_success_criteria_fails_when_one_is_missed` | 正常 | 片方だけ満たす 2 通りは、どちらも「満たさない」 |
| 27 | `test_success_criteria_boundary_is_ten_percent` | 境界 | ちょうど 10%（100 に対して 90）は満たす、わずかに足りなければ満たさない |
| 28 | `test_success_criteria_without_reference` | 境界 | 比べる相手の MAE が欠損・0 のときは判定が `None`、エラーにしない |
| 29 | `test_success_criteria_is_json_serializable` | 異常 | `json.dumps(..., allow_nan=False)` で書ける |
| 30 | `test_train_and_evaluate_notebooks_exist` | 正常 | 04・05 があり、出力がない（既存のテストの対象に入る） |
| 31 | `test_training_report_was_made_from_full_data` | 正常 | `reports/training.json` が `mode=full`、特徴量の一覧が `FEATURE_NAMES` と同じ、6 年と 3 年の両方の検証の MAE が数値、採った期間がそのどちらか、**テストの年が入っていない** |
| 32 | `test_metrics_report_was_made_from_full_data` | 正常 | `reports/metrics.json` が `mode=full`、テストの年に 2 都市・4 つの季節・4 つの予測（モデルと 3 つのベースライン）があり、成功基準の判定が都市ごとに入っている、`model_version` がモデルのファイルと同じ |
| 33 | `test_reports_have_no_local_paths_or_secrets` | 異常 | 2 つの JSON に手元のパス・シークレットらしい文字列・NaN がない |
| 34 | `test_committed_model_matches_current_features` | 正常 | `models/cloud_base.joblib` を読めて、特徴量の一覧がいまの `FEATURE_NAMES` と同じ（特徴量を変えてモデルを作り直し忘れたら気づく） |
| 35 | `notebooks/04_train.ipynb`・`05_evaluate.ipynb`（nbmake） | 正常 | サンプルの設定で最後まで実行でき、外部と通信しない |

- 期待値は、手で書いた小さな入力から見て分かるもの、`app/services/solar.py` を直接呼んだ値（その関数は #7 で NOAA の値と照合済み）、spec の式・上限・年だけ。**MAE や予測の実際の値（何 m）をテストの期待値にしない**。
- Red の確認：`features` → `split` → `train` → `model` → `evaluate` → ノートブックの順。骨組み（`NotImplementedError`）で失敗することを実行して確かめ、骨組みでも通るテストは一覧にする。
- Green の後、実装をわざと壊してテストが失敗することを確かめる（#8〜#10 と同じ）。

## 追加する依存パッケージ

| パッケージ | 理由 | 代替案 |
|---|---|---|
| `lightgbm`（依存グループ `ml`） | 学習。CLAUDE.md の技術スタックにある。一緒に `scipy` が入る（`numpy` は pandas で導入済み） | なし（技術スタックで決まっている） |
| `joblib`（依存グループ `ml`） | spec の成果物 `models/cloud_base.joblib` の保存・読み込み | LightGBM の文字の形式（`save_model`）で保存すれば不要。読み込みでコードが実行されない点は安全だが、spec のファイル名と違う。標準ライブラリの `pickle` でも書けるが、安全性は joblib と同じ |

- `scikit-learn` は入れない（LightGBM の `train` を直接使い、評価は既存の `ml/evaluate.py`）。
- どちらも依存グループ `ml` に入れるので、API のイメージ（`Dockerfile`）には入らない。**#12 で、API のイメージに `lightgbm`・`joblib`（と pandas）をどう入れるかを決める必要がある**（#10 の申し送りと同じ問題）。
- バージョンは `uv add` が選んだものを報告する。型の情報のためのパッケージが別に要る場合は、足す前に聞く。

## セキュリティ上の注意

- 入力検証：利用者の入力はない（API のエンドポイントは足さない）。ノートブックの切り替えは `sample`／`full` 以外をエラーにする。`ml/` の関数は、知らない都市・UTC でない時刻・列の不足・行のずれ・特徴量の列の違いを拒否する。
- シークレット：使わない。`.env` は読まない。`reports/*.json`・`docs/model-card.md` は git に入るので、パス・環境変数を書き出さない（テスト 33）。
- **モデルのファイル（joblib ＝ pickle）は、読み込むとコードを実行できる形式**。読み込むのは、このリポジトリで作って git に入れた、決まったパスのファイルだけにする（利用者の入力・環境変数からパスを作らない）。#12 への申し送りに書く。PR では中身の差分を見られないので、`reports/training.json` に `model_version` と特徴量の一覧を書き、テスト 34 で突き合わせる。
- 外部通信（ホスト・タイムアウト）：**アプリ・テスト・ノートブックからはなし**。テスト・nbmake・全期間の実行は `--network none`。
- **作業のために取得するもの**：`uv add`・イメージの作り直しで PyPI から `lightgbm`・`joblib`・`scipy`（と、その依存）。`libgomp1` が要る場合は Debian のパッケージ 1 つ。これ以外を取得する必要が出たら、取得する前に伝える。
- データの利用条件：ノートブックの先頭と `docs/model-card.md` に出典を書く（Open-Meteo は CC BY 4.0、IEM）。

## 実行のたびに枠を使うものの見積もり

- 外部API（Open-Meteo・IEM）：**0 回**。
- GitHub Actions：PR の作成で 1 回、レビュー後の修正と dev-log で 1〜2 回の計 2〜3 回を目安。依存が増えるので、1 回の時間は少し延びる。

## リスク・未決事項

1. **実装は途中で一度止まる**（質問 2 が推奨どおりの場合）。(a) 04 を全期間で実行 → 検証の年の数値と、6 年・3 年のどちらを採ったかを報告 →（人間の了解）→ (b) 05 を全期間で実行。05 を実行した後は、モデルを変えない。
2. **成功基準に届かない可能性がある**。とくに基準 2（上限より下の行の MAE を概算式より 10% 改善）。MAE を目的関数にすると、上限の行が多い（東京 4 割・ベルリン 7 割）ので、予測が上限に寄り、上限より下の行の誤差が大きくなりうる。検証の年の数値（04）で見えるので、(a) の報告に書く。届かなかったときの扱いは質問 1。
3. **推論のときに取れない特徴量が入るおそれ**。`pressure_msl` は、予報の API では未確認（spec 7「#12 で確認する」）。今回は過去データの列（確認済み）を使うので #11 の作業は止まらないが、#12 で取れないと分かったら、その特徴量を外して学習し直すことになる（学習は数十秒の見込み）。`model-card.md` と #12 への申し送りに書く。
4. **学習と推論の入力の差は測れない**（質問 8）。学習は再解析、推論は予報。テストの年の数値は「再解析を入力にしたとき」のもので、API の実際の精度はこれより悪い可能性がある。
5. **検証の年を 3 つのことに使う**（打ち切りの回数、6 年と 3 年の比較、(a) の報告）。検証の年の数値は、テストの年より良く出やすい。テストの年は 05 でだけ使う。
6. **学習の再現性**。同じイメージ・同じ依存のバージョンなら同じ結果になる見込みだが、LightGBM のバージョンが変わると数値が変わりうる（Dependabot の更新など）。`reports/` とモデルは、作ったときのバージョンを `reports/training.json` に書く。
7. **モデル（バイナリ）を git に入れる**。大きさは実行して確かめる（数百 KB〜数 MB の見込み）。特徴量を変えたら作り直す必要があり、忘れるとテスト 34 で気づく（数値の作り直し忘れは CI では分からない。#10 と同じ）。
8. **この PC では numpy を import できない**ので、学習・テスト・ノートブックはすべて `Dockerfile.dev` のイメージの中で実行する。
9. **Issue #21 の本文を読めていない**（`gh` がこの環境にない）。spec の機能 #11 と同じ内容という前提。
10. 範囲は「特徴量・学習・評価・model-card」で、#10 より大きい。分割案は質問 9。

## ブロッカー（人間の対応が必要なこと）

1. **依存の追加の承認**：`lightgbm`・`joblib`（依存グループ `ml`）。必要なら `Dockerfile.dev` に `libgomp1`。
2. **Issue #21 の本文**：spec の機能 #11 にない要件が書かれていれば教えてください。なければ spec と同じ内容として進めます。

2026-10-13 の承認時の扱い：1 は、計画の承認（「推奨で」）に含まれるものとして扱う（`uv add` の前に、入れるパッケージをもう一度伝える）。2 は、追加の要件の連絡がなかったので、spec と同じ内容として進める。

外部APIの未確認の項目は、#11 の作業では **ない**（外部APIを呼ばない。使うのは #8 で確認済みの過去データの列だけ）。予報の側の確認は #12（リスク 3）。

## 質問

それぞれ推奨を 1 つ書いています。「推奨で」と返してもらえれば、その内容で進めます。

**回答（2026-10-13）：「推奨で」。1〜9 はすべて推奨の内容で進める。**

1. **成功基準に届かなかったときの扱い**（#10 からの申し送り）：推奨は **テストの年の結果を見た後は、モデル・特徴量・成功基準を変えない。届かなければ「届かなかった」と、どの都市のどの基準かを `model-card.md` に書き、#11 は完了にする**（受け入れ条件は「04・05 完了、比較を記録」）。改善は別の Issue にする。テストの年を見てから直すと、テストの年に合わせたことになるため。承認されたら spec 9 に書きます。
2. **04 の後で一度止まること**：推奨は **止まる**。検証の年の数値と、6 年・3 年のどちらを採ったかを報告し、了解をもらってから 05（テストの年）を実行する。この時点なら、検証の年の数値を見て特徴量や設定を直しても、テストの年は使っていない。
3. **特徴量**：推奨は **上の表の 17 列**。spec の候補すべてに、**`precipitation_mm`（前の 1 時間の降水量）を 1 つ足す**。EDA でシーリングとの関係があり（`docs/eda.md` 6 節。東京で −0.37）、予報の API でも確認済みの項目のため。spec の候補にないので、不要なら 16 列にします。`weather_code` は入れない（候補になく、雲量・降水と重なる）。
4. **モデルと設定**：推奨は **2 都市で 1 つの LightGBM、目的関数は MAE、設定は固定（探索しない）、打ち切りの回数だけ検証の年で決める**。設定の値は、既定値を基本にして Red の前に一覧で示します。探索や、目的関数の比較（MAE と二乗誤差）を入れると、検証の年を使う回数と作業が増えます。
5. **6 年と 3 年の比べ方**：推奨は **検証の年の、2 都市を合わせた全体の MAE 1 つで決める**（3 年のほうが小さければ 3 年、同じか大きければ 6 年）。spec の文（「検証の年の MAE で比べる」）にいちばん近い。都市別・上限より下の行の MAE は参考として並べるだけ。
6. **モデルのファイルを git に入れること**：推奨は **入れる**（`models/cloud_base.joblib`）。学習データは git にないので、CI・CD ではモデルを作れない。#12・#14 のイメージに入れるには、リポジトリにある必要がある。`model_version` は `2026-10-<実装の日>-lgbm-v1`（コードの定数。実行のたびに変わらない）。
7. **`reports/training.json` を足すこと**：推奨は **足す**。6 年と 3 年の比較の数値を `model-card.md` に写す、もとのファイルが要る（04 の結果。05 の `reports/metrics.json` と分ける）。spec の成果物の表に 1 行足します。
8. **学習と推論の入力の差（model-card）**：推奨は **今回は測らず、分かっていることだけを書く**（学習は再解析・推論は予報であること、テストの年の数値は再解析を入力にしたものであること、`docs/eda.md` 5 節の「Open-Meteo の値は METAR の値より関係が弱い」）。測るには過去の予報のデータ（spec 7 で未確認の API）が要るので、やるなら別の Issue にする。
9. **分割**：推奨は **分けない**（1 つの PR）。分ける場合は「特徴量と学習（04）」と「評価と model-card（05）」の 2 つですが、spec の機能 #11 は 1 つで、04 の結果を 05 がそのまま使うので一緒にします。

## 実装時の変更

（2026-10-13）

- **学習の設定を示したのが、Red の後になった**（計画では「Red の前に一覧で示す」）。Red の結果と一緒に示し、「実装へ進んで」の返事をもらってから実装した。テストは設定の値に依存していない。
- **テストの数が計画（34 件）より多い**（新しいテストは、関数で 43、パラメータで分かれた場合を数えると 55）。境界・異常の場合を分けたため。弱めたテスト・skip したテストはない。
  - 足したもの：`rows_in_years` の「行の番号を保つ・UTC でない時刻を拒否」、`success_criteria` の「比べる相手を取り違えない」「モデルの側に値がない」、`predict_m` を学習したモデルで呼ぶテスト、太陽高度が都市の位置を使うこと。
  - テスト 31 の「テストの年が入っていない」は、`reports/training.json` のどの階層にも `test` というキーがないこと、学習・検証の年の一覧に 2025 がないことで確かめている。
- **`success_criteria` の `meets_both`**：片方でも判定できない（`None`）ときは `None`（計画には書いていなかった）。
- **判定の式**：「ちょうど 10%」が浮動小数の誤差でずれないように、`(相手 − モデル) >= 0.10 × 相手` の形にした（`1 − モデル / 相手 >= 0.10` だと、100 に対する 90 が満たさない側になることを実行して確かめた）。
- **`fit` は、列が `FEATURE_NAMES`（名前と順）でなければ `ValueError`**。LightGBM は予測のときに列の名前を見ず、順を変えて渡すとエラーにならずに違う予測になる（実行して確かめた）。`predict_m` も同じ理由で、順の違いを拒否する。
- **依存**：`lightgbm` 4.7.0・`joblib` 1.6.0 と一緒に、`scipy` 1.18.1・`narwhals` 2.27.1（どちらも lightgbm の依存）・`cloudpickle` 3.1.2 が `uv.lock` に入った。`narwhals`・`cloudpickle` は、計画には名前を書いていなかった。
- **`Dockerfile.dev` に `libgomp1` を足した**（計画の見込みどおり、`python:3.14-slim` になく、LightGBM を import できなかった）。
- **mypy**：`joblib` に型の情報がなかったので、`pyproject.toml` で `joblib` だけ `ignore_missing_imports` にした。`lightgbm` には型の情報がある。
- **`ml/features.py` の `_local_time`**：「年の何日目」も返せるようにした（既存の `local_hour`・`season` の結果は変わらない。既存のテストが通る）。`ml/split.py` も、時刻の確認を `split` と `rows_in_years` で共有する形に直した。
- **`reports/training.json` に `lightgbm_version`・`selection_rule`・`max_rounds`・`early_stopping_rounds` を入れた**。`reports/metrics.json` には、成功基準を判定した分割の名前と、基準の割合（0.1）を入れた。
- **再実行の確認**：04 を全期間で 2 回実行し、`models/cloud_base.joblib` と `reports/training.json` がバイト単位で同じになった。
- **04 の後で止まった時点の報告**：検証の年で、基準 2（上限より下の行の MAE）が 2 都市とも概算式より悪かった。「設定を直さずに 05 へ進む」を選んだ（人間の回答「推奨で進めて」）。
- **結果**：テストの年で、基準 1 は 2 都市とも満たし、基準 2 は 2 都市とも満たさなかった。質問 1 の回答のとおり、モデルは変えず、`docs/model-card.md` に書いて #11 を完了にした。
- **`docs/model-card.md` の数値の突き合わせ**：作業用のスクリプトで、文書の中の数値がすべて `reports/training.json`・`reports/metrics.json` にあることを確かめた（日付・節の番号・式の係数などを除く）。スクリプトはリポジトリに入れていない。
- **実装をわざと壊す確認**：12 通り（上限に収めない、列の順を見ない、現地の日付でなく UTC で数える、都市の位置を固定する、欠損を埋める、`>=` を `>` にする、比べる相手を取り違える、など）で、どれもテストが失敗した。

### レビュー後の修正（2026-10-13）

- `docs/model-card.md`：基準 2 を満たさなかった「考えられる理由」を消した（「予測が上限の側に寄る」と書いたが、件数はそれを示していなかった）。東京の夏の誤差と、除いた行の多さを、理由のように並べていた文を分けた。
- `docs/spec.md`：`reports/metrics.json` の改善率は、割合で小数 4 桁（「小数 2 桁」の例外）と書いた。
- `tests/ml/test_model.py`：モデルの本体が LightGBM のモデルでないファイルを拒否する場合を足した（`ml/model.py` のカバレッジが 100% になった）。
- 見送ったもの（別の Issue の候補）：ノートブック 02〜05 の重複（サンプルの読み込み、ベースラインの予測）を `ml/` に移すこと、モデルのファイルの SHA-256 を `reports/training.json` に書くこと、`.gitattributes` に `models/** binary` を足すこと。
- まだ確かめていないこと：CI（`ubuntu-latest`）で LightGBM を import できるか。PR の CI で確かめる。
