# 計画：#17 モデルの改善（Issue #27）

状態：承認済み（2026-10-13。質問 1〜7 はすべて推奨どおり。Issue は #27、ブランチは `feature/issues_27`）

## 目的と受け入れ条件

spec.md「14. 機能一覧」より：

> | 17 | モデルの改善 | #16 で決めた案を、計画で決めた手順で比べる。テストの年（2025）は最後に 1 回だけ評価し、成功基準の判定と前のモデルとの比較を `docs/model-card.md` に書く。採る場合は `model_version` を替え、`/cloud-base` のテストが通る |

spec.md「9. モデルの改善」より：

> - 案と設定を選ぶのに使うのは、学習と検証の年（2018〜2024）だけ。
> - テストの年は、#17 で案と設定をすべて決めた後に、1 回だけ評価する。2025 年は #11 で 1 回見ている。#17 の結果は「2 回目の評価」と `docs/model-card.md` に明記する。
> - 試す案の数と、選ぶ決まり（どの指標が、どれだけ良ければ採るか）は、#17 の計画に先に書く。計画にない案は試さない。
>   - 検証の年（2024）だけで選ぶか、年ごとに順に検証するかは、#16 の結果を見て #17 の計画で決める。
> - 成功基準（上の 1・2、10%）は変えない。
> - 届かなかった場合も、結果を `docs/model-card.md` に書いて終わる。届くまで繰り返さない。
> - 採る場合、`ml/model.py` の `predict_m` の入口（特徴量の表 → メートル）は変えない。`app/` の側で替わるのは、モデルのファイルと `model_version` だけ。

背景（`docs/model-card.md` 7 節・10 節）：

- いまのモデル（`2026-10-13-lgbm-v1`。以下 v1）は、成功基準の 2 つ目（上限より下の行の MAE が概算式より 10% 以上小さい）に 2 都市とも届いていない。検証の年でも同じ（東京 426.65 対 371.76、ベルリン 386.08 対 349.52）。
- #16 の結果：v1 は高すぎる（偏りは東京 320.94、ベルリン 234.8）。概算式に負けているのは低い帯（0〜300 m：東京 415.1 対 92.47、ベルリン 461.88 対 79.1）。
- #16 で選んだ案は **D（上限より下の行に重みを付ける）と A（2 段階）**。B は「当たると言い切れない」として人間の判断に任せてある（質問 1）。

完了の確認方法：

1. `pytest --cov=app --cov=ml` が通る（カバレッジ 80% 以上）。`ruff check .`・`ruff format --check .`・`mypy app ml` が通る
2. `pytest --nbmake notebooks/` が、サンプルデータで、外部と通信せずに通る（01〜08）
3. 全期間で `07_improve` を 2 回実行し、`reports/improvement.json` と候補のモデルのファイルが同じになる。テストの年の行から作った値が入っていない（テストで確かめる）
4. `07` の `current`（v1 と同じ設定）の、検証 2024 の都市ごとの行数と MAE が、`reports/training.json` の値と同じ（テストで確かめる。違えば環境か実装の誤り）
5. 全期間で `08_evaluate_improved` を実行し、`reports/metrics_improved.json` ができる（設定が 1 つも選ばれなかった場合は実行しない。下の「選ぶ決まり」）。v1 の側の数値が `reports/metrics.json` と同じ（テストで確かめる）
6. `models/cloud_base.joblib`（採らない場合）・`reports/training.json`・`reports/metrics.json`・`reports/error_analysis.json`・`reports/baseline.json` が変わっていない（ハッシュで確かめる）
7. `docs/model-card.md` 11 節に、比べた設定・選ぶ決まり・検証の結果・テストの年の結果（「2 回目の評価」と明記）・v1 との比較・採ったかどうかが書いてある。**表は `reports/*.json` からスクリプトで作り直して、1 行ずつ同じことを確かめる**（#16 の学び）
8. 採る場合：`model_version` が替わり、`/cloud-base` のテスト（`tests/app/`）が通る。Docker のイメージがビルドでき、`/cloud-base` が新しい `model_version` を返す
9. spec の機能一覧 #17 を更新する（PR の CI が通った後）

## 今回やらないこと

- 下の表にない案・設定を試すこと（B、C、E、F、目的関数の変更、`num_leaves` などの探索、特徴量の追加）
- 結果を見た後に、設定・決まり・成功基準を変えること。届かなくても繰り返さない
- 新しいモデルの誤差の分析（`06_error_analysis` のやり直し。必要なら別の Issue）
- 予報を入力にしたときの精度（過去の予報のデータが要る。spec 7 で未確認）
- `app/` のコードの変更（採る場合も、替わるのはモデルのファイルと `model_version` だけ）
- `02_eda`・`03_baseline` の変更。`04`〜`06` は、採る場合の「ファイルの置き方」の行だけ（下の表）
- UI（Issue #25 に含まれていた別の機能）

## 比べる設定（6 つ ＋ 参考 1 つ）

特徴量（17 列）、学習の年の決め方、`learning_rate` 0.05・`num_leaves` 31・`min_data_in_leaf` 20・`seed` 0・スレッド 1 つ、木の数の決め方（50 回続けて良くならなければ止める。上限 2,000）は、v1 と同じ。変えるのは下の 1 か所ずつ。

| 名前 | 案 | 内容 |
|---|---|---|
| `current` | 参考 | v1 と同じ設定。選ぶ対象にしない（比べる相手） |
| `weighted_2`・`weighted_4`・`weighted_8` | D | 目的関数は MAE のまま。正解が上限より下の行の重みを 2・4・8 にする（上限の行は 1）。木の数を決める検証の MAE にも、同じ重みを付ける |
| `two_stage_50`・`two_stage_40`・`two_stage_30` | A | モデルを 2 つ学習する。(1) 分類：正解が上限より下か（目的関数は 2 値の対数損失。木の数は検証の対数損失で決める）。(2) 回帰：正解が上限より下の行だけで学習（MAE。木の数は検証の年の上限より下の行の MAE で決める）。予測は、(1) の確率が閾値（0.5・0.4・0.3）以上なら (2) の値、未満なら上限。最後に 0〜1,524 m に収める |

- 学習の回数：1 つの検証の年につき 6 回（`current`、重み 3 つ、分類、回帰。閾値の 3 つは同じ 2 つのモデルを使う）。
- **重みの値（2・4・8）と閾値（0.5・0.4・0.3）に、データ上の根拠はない**（質問 2）。どちらも「上限より下」と答えやすくする向きで、強さを 3 段階にしただけ。
- D のうち「目的関数を変える」は試さない（設定の数を増やさないため。質問 1）。

## 検証のしかた：2 つの年で順に検証する

| 名前 | 学習の年 | 検証の年 |
|---|---|---|
| `validation_2023` | 2018〜2022 | 2023 |
| `validation_2024` | 2018〜2023 | 2024 |

- 理由（#16 の結果から）：
  - 2024 年は、すでに 3 回使っている（v1 の木の数、学習期間の比較、#16 で案 D・A を選んだ分析）。2024 年だけで 6 つから選ぶと、2024 年に合わせることになる。
  - #16 では、1 年ぶんを細かく分けると行が少なかった（都市 × 季節 × 帯で 24 行の組）。都市ごとの数値も、1 年では 2 つしかない。
- 2022 年より前を検証の年にしない理由：観測のしかたが変わる前の年だから（ベルリンは 2023 年からすべて自動観測、東京は 2023 年から `CAVOK` が増えた。spec「9. 分割と評価」）。2023・2024 年は、どちらも変化の後。
- `validation_2024` は、spec の分割（学習 2018〜2023、検証 2024）と同じ。**選ばれた設定の、`validation_2024` で学習したモデルを、そのまま最終のモデルにする**（学習し直さない。v1 と同じ決まり）。
- 上限より下の行は、2023 年が東京 1,450・ベルリン 2,836、2024 年が東京 1,797・ベルリン 2,875（2026-10-13 に行数だけ数えた）。

## 選ぶ決まり（結果を見る前に決める）

設定 × 検証の年 × 都市（2 × 2 ＝ 4 つ）ごとに、成功基準と同じ 2 つの値を出す（`ml/evaluate.py` の `success_criteria`。丸める前の値）。

- 改善 1：全体の MAE が、`always_cap` より小さい割合
- 改善 2：上限より下の行の MAE が、`rule_of_thumb` より小さい割合

1. **残す設定**：4 つすべてで、改善 1 が 10% 以上（基準 1 を満たす）。判定できない（比べる相手がない）ものは、満たさないとして扱う。
2. **点**：4 つの改善 2 のうち、最も小さい値。
3. **選ぶ**：残った設定のうち、点が最も大きいもの。同じなら、表の上のもの（`weighted_2` → … → `two_stage_30` の順）。
4. **テストの年に進む条件**：選んだ設定の点が、`current` の点より大きい。残った設定がない・`current` 以下なら、**テストの年は評価しない**。v1 のまま、結果を `docs/model-card.md` に書いて終わる。
5. **テストの年（2025）**：選んだ 1 つだけを、1 回評価する。
6. **採る条件**：テストの年で、2 都市とも成功基準の 1・2 を両方満たす（`meets_both`）。満たさなければ採らない（v1 のまま。結果は書く）。質問 4。

- この決まりは `ml/improve.py` の関数にして、テストを付ける（手で書いた表で確かめる）。ノートブックは関数を呼ぶだけ。
- 「点」に最も小さい値を使うのは、成功基準が「都市ごとに満たす」だから（片方の都市・片方の年だけ良い設定を選ばない）。

## 変更・追加するファイル

| ファイル | 内容 |
|---|---|
| `ml/train.py` | `fit` に `below_cap_weight`（既定 1.0。1.0 のときは重みを渡さず、いまと同じモデルになる）。`fit_classifier`（上限より下かの分類）、`fit_below_cap`（上限より下の行だけの回帰）を足す |
| `ml/model.py` | `CloudBaseModel` に `classifier`・`below_cap_threshold`（どちらも既定 `None`）を足す。`predict_m` は、2 つあれば 2 段階で予測する（引数と戻り値は変えない）。`save`・`load` は 2 段階のファイル（キーが 2 つ多い）も扱う。**1 段階のモデルのファイルの中身は、いまと同じ 5 キーのまま**（v1 のファイルが変わらない）。`MODEL_VERSION_V1`・`MODEL_VERSION_V2` を足す（`MODEL_VERSION` は、採るまで V1） |
| `ml/split.py` | `ROLLING_FOLDS`（上の 2 つ） |
| `ml/improve.py`（新規） | 設定の一覧（名前・順・重み・閾値）、`fit_candidates`（1 つの検証の年について、設定ごとのモデルを作る）、`select`（選ぶ決まり 1〜4）、`adopt`（採る条件 6） |
| `tests/ml/test_train.py`・`test_model.py`・`test_split.py` | テスト 1〜16 |
| `tests/ml/test_improve.py`（新規） | テスト 17〜27 |
| `notebooks/07_improve.ipynb`（新規） | 設定の比較。**テストの年は読み込んだ直後に落とす**。`reports/improvement.json` と、選んだ設定のモデル `models/cloud_base_v2.joblib` を書く。出力を消してコミット |
| `notebooks/08_evaluate_improved.ipynb`（新規） | 選んだ設定のモデルを、テストの年で評価する。v1 と並べ、成功基準を判定する。`reports/metrics_improved.json` を書く |
| `reports/improvement.json`・`reports/metrics_improved.json`（新規） | 下の「成果物のキー」。全期間で実行したもの |
| `tests/test_notebooks.py` | テスト 28〜37。既存のテストの直し（下の「既存のテストの変更」） |
| `docs/model-card.md` | 11 節「モデルの改善（#17）」。採る場合は、冒頭の `model_version` と 1 節の要点を直し、4〜7・10 節が v1 の記録であることを書く。v1 の数値は消さない |
| `docs/spec.md` | 9「モデルの改善」に「#17 で決めたこと・結果」、ノートブックの表に 07・08、機能一覧 #17 の状態。採る場合は `model_version` の記述（5 節の例、9 節の定数、5 節の「成功基準に届いていないものをそのまま出す」）。**書く前に、変更の一覧を示して聞く** |
| `CLAUDE.md` | 「ディレクトリ」の `notebooks/` の行に 07・08 を足す（1 行。質問 6） |
| `app/`、`ml/features.py`、`ml/evaluate.py`、`pyproject.toml`、`uv.lock`、`Dockerfile*`、`ci.yml`、`tests/app/`、`tests/fixtures/` | 変更なし |

### 採る場合だけ行う変更（ファイルの置き方。質問 5）

v1 の記録（04〜06 と、その 3 つの reports）を、再実行できる形で残す。

| 変更 | 内容 |
|---|---|
| モデルのファイル | `models/cloud_base.joblib`（v1）を `models/cloud_base_v1.joblib` に名前を変える。`models/cloud_base_v2.joblib` を `models/cloud_base.joblib` にする（API が読むパスは変えない） |
| `ml/model.py` | `MODEL_VERSION = MODEL_VERSION_V2` |
| `04_train` | 書く先を `cloud_base_v1.joblib` に、`model_version` を `MODEL_VERSION_V1` と明示（2 行） |
| `05_evaluate`・`06_error_analysis` | 読む先を `cloud_base_v1.joblib` に（1 行ずつ） |
| `07_improve`・`08_evaluate_improved` | 書く先・読む先を `cloud_base.joblib` に（1 行ずつ） |
| 確認 | 04〜08 を全期間で実行し直し、**5 つの reports と 2 つのモデルのファイルのハッシュが、変更の前と同じ** であることを確かめる（同じモデル・同じ設定の再実行。テストの年の「評価の回数」には数えない） |

採らない場合：`models/cloud_base_v2.joblib` はコミットしない（作業ツリーに残る。消すかどうかは人間に聞く）。`reports/` の 2 つと 07・08 はコミットする。

### 成果物のキー

`reports/improvement.json`（07）：

| キー | 内容 |
|---|---|
| `mode`、`cap_m`、`feature_names`、`lightgbm_version` | 既存の reports と同じ |
| `reference_model_version` | v1 の `model_version` |
| `params`、`classifier_params`、`max_rounds`、`early_stopping_rounds` | 学習の設定 |
| `folds` | `{"validation_2023": {"train_years": [...], "validation_years": [2023]}, "validation_2024": {...}}` |
| `settings` | 設定の名前 → `{"kind": "current"/"weighted"/"two_stage", "below_cap_weight", "below_cap_threshold"}`（表の順） |
| `selection_rule` | 決まりの文（英語の 1 文）と `min_improvement`（0.1） |
| `results` | 設定 → 検証の年の名前 → `{"n_train", "best_iteration", "best_iteration_classifier"（2 段階だけ。ほかは `null`）, "validation": （`evaluate.report` の形）, "criteria": {都市: `success_criteria` の 5 キー（小数 4 桁）}}` |
| `validation_baselines` | 検証の年の名前 → `rule_of_thumb`・`always_cap` → `evaluate.report` の形 |
| `selection` | 設定 → `{"eligible": 真偽, "score": 小数 4 桁 または `null`}`（`current` も入れる） |
| `selected` | 選んだ設定の名前。テストの年に進まない場合は `null` |

`reports/metrics_improved.json`（08）：

| キー | 内容 |
|---|---|
| `mode`、`cap_m`、`train_years` | 既存と同じ |
| `model_version`、`previous_model_version` | 新しいモデルと v1 |
| `setting` | 選んだ設定の名前（`improvement.json` の `selected` と同じ） |
| `test_year_evaluation` | `"second"`（2025 年は #11 で 1 回見ている） |
| `predictions` | 予測の名前 → 説明（`model`・`previous_model`・`rule_of_thumb`・`always_cap`） |
| `success_criteria_split`、`success_criteria_min_improvement` | `metrics.json` と同じ |
| `success_criteria`、`previous_success_criteria` | 都市 → 5 キー（新しいモデル、v1） |
| `adopted` | 2 都市とも `meets_both` なら `true` |
| `splits` | `validation`・`test` → `{"years", "predictions": {予測の名前: `evaluate.report` の形}}` |

`rule_of_thumb_metar`（参考）は、今回の 2 つには入れない。

### 既存のテストの変更

弱めるのではなく、「v1 の記録」と「API が出すモデル」を分けるための直し。採らない場合も、意味は同じ（`MODEL_VERSION` が V1 のまま）。

| テスト | いま | 直した後 |
|---|---|---|
| `test_training_report_was_made_from_full_data`、`test_error_analysis_report_was_made_from_full_data` | `model_version == model.MODEL_VERSION` | `== model.MODEL_VERSION_V1` |
| `test_committed_model_matches_current_features_and_reports` | API のファイルが `MODEL_VERSION`・`metrics.json` と合う | v1 のファイル（採る前は `cloud_base.joblib`、採った後は `cloud_base_v1.joblib`）が `MODEL_VERSION_V1`・`training.json`・`metrics.json` と合う。API のファイルのほうはテスト 37 |
| `tests/ml/test_model.py` の `test_model_version_has_expected_form` | `MODEL_VERSION` の形 | テスト 15 に広げる |

## テスト一覧（先に書く順）

| # | テスト名 | 種類（正常/異常/境界） | 確かめること |
|---|---|---|---|
| 1 | `test_fit_default_weight_gives_same_model` | 境界 | `below_cap_weight=1.0` は、指定しないときと同じモデル（v1 が再現できる） |
| 2 | `test_fit_below_cap_weight_lowers_predictions` | 正常 | 同じ特徴量に上限の行と低い行が混ざった手書きの表で、重みなしは上限、重みを大きくすると低い値を答える |
| 3 | `test_fit_rejects_invalid_weight` | 異常 | 0・負・NaN・無限大は `ValueError` |
| 4 | `test_fit_classifier_learns_an_obvious_relation` | 正常 | 手書きの表で、上限より下の行の確率が高く、上限の行が低い。値は 0〜1 |
| 5 | `test_fit_classifier_rejects_single_class_empty_or_misaligned` | 異常 | 学習の行がすべて同じ側・正解のある行がない・行のずれ・列の違いは `ValueError` |
| 6 | `test_fit_below_cap_uses_only_rows_below_cap` | 正常 | 上限の行・正解のない行を足しても、同じモデルになる |
| 7 | `test_fit_below_cap_rejects_no_rows_below_cap` | 異常 | 学習か検証に上限より下の行がなければ `ValueError` |
| 8 | `test_new_fits_are_reproducible_and_do_not_modify_input` | 正常 | 2 回学習して同じ予測。入力を書き換えない |
| 9 | `test_predict_two_stage_uses_cap_below_threshold` | 境界 | 確率が閾値より小さければ上限、閾値ちょうど・大きければ回帰の値 |
| 10 | `test_predict_two_stage_is_within_zero_and_cap` | 境界 | 2 段階でも 0〜1,524 に収まる。行の番号・名前・列の確認は 1 段階と同じ |
| 11 | `test_two_stage_requires_classifier_and_threshold_together` | 異常 | 片方だけ、閾値が 0 以下・1 以上は `ValueError` |
| 12 | `test_save_and_load_two_stage_give_same_predictions` | 正常 | 2 段階のモデルを保存して読み直すと、同じ予測・同じ閾値 |
| 13 | `test_save_one_stage_keeps_five_keys` | 境界 | 1 段階のモデルのファイルの中身は、いまと同じ 5 キー |
| 14 | `test_load_rejects_unexpected_two_stage_content` | 異常 | 分類のモデルが LightGBM のモデルでない・閾値の型や範囲が違う・2 つのキーの片方だけ・知らないキーは `ModelLoadError` |
| 15 | `test_model_versions_have_expected_form` | 正常 | V1 は spec の `2026-10-13-lgbm-v1`。V2 も同じ形で、V1 と違う。`MODEL_VERSION` はどちらか |
| 16 | `test_rolling_folds_follow_plan` | 正常 | 2 つ。学習の年は検証の年より前だけ。2025 年がどこにもない。最後の 1 つは spec の分割と同じ |
| 17 | `test_settings_follow_plan` | 正常 | 名前と順、重み 2・4・8、閾値 0.5・0.4・0.3。`current` は選ぶ対象でない |
| 18 | `test_fit_candidates_returns_a_model_for_each_setting` | 正常 | 手書きの表で、設定ごとのモデルができる。`current` は `train.fit` と同じ予測。閾値の 3 つは同じ 2 つのモデルで、閾値だけが違う |
| 19 | `test_select_requires_criterion_1_in_every_city_and_fold` | 異常 | 4 つのうち 1 つでも基準 1 を満たさなければ、残らない |
| 20 | `test_select_score_is_smallest_criterion_2_improvement` | 正常 | 点は 4 つの改善 2 の最も小さい値 |
| 21 | `test_select_picks_highest_score_among_eligible` | 正常 | 残った中で点が最も大きいもの。残らなかった設定は、点が大きくても選ばない |
| 22 | `test_select_tie_goes_to_earlier_setting` | 境界 | 点が同じなら、表の上のもの |
| 23 | `test_select_none_unless_better_than_current` | 境界 | 残った設定がない、点が `current` と同じ・小さい場合は `None` |
| 24 | `test_select_treats_unjudged_as_not_eligible` | 境界 | 判定が `None`（上限より下の行がない都市など）なら、残らない・点は `None` |
| 25 | `test_select_rejects_missing_setting_fold_or_city` | 異常 | 設定・検証の年・都市が欠けた表は `ValueError` |
| 26 | `test_adopt_requires_both_criteria_in_every_city` | 境界 | すべての都市で `meets_both` が真のときだけ真。`None` は偽。都市がなければ `ValueError` |
| 27 | `test_improve_does_not_modify_input` | 正常 | `fit_candidates`・`select`・`adopt` が入力を書き換えない |
| 28 | `test_improve_notebooks_exist` | 正常 | 07・08 があり、出力なし・手元のパスなしの確認の対象に入る |
| 29 | `test_improvement_report_was_made_from_full_data` | 正常 | `mode` が `full`、検証の年と設定が計画どおり、設定 × 検証の年ごとに 2 都市・4 季節と判定の 5 キーがある。`selected` は `null` か、残った設定の名前 |
| 30 | `test_improvement_report_reference_matches_training_report` | 正常 | `current` の `validation_2024` の、都市ごとの行数・MAE・木の数が `reports/training.json` と同じ |
| 31 | `test_improvement_report_has_no_test_year` | 異常 | `test`・`2025` がどのキー・年の一覧にもない |
| 32 | `test_metrics_improved_exists_only_when_a_setting_was_selected` | 境界 | `selected` が `null` ならファイルがない。名前があればファイルがある |
| 33 | `test_metrics_improved_report_was_made_from_full_data` | 正常 | （ファイルがある場合）検証 2024・テスト 2025、4 つの予測、判定の 5 キー、`setting` が `selected` と同じ、`adopted` が判定と合う、`test_year_evaluation` が `second` |
| 34 | `test_metrics_improved_previous_model_matches_metrics_report` | 正常 | v1 の側の、都市ごとの数値と成功基準の判定が `reports/metrics.json` と同じ |
| 35 | `test_metrics_improved_validation_matches_improvement_report` | 正常 | 新しいモデルの検証 2024 の都市ごとの数値が、`improvement.json` の選んだ設定の値と同じ |
| 36 | `test_new_reports_have_no_local_paths_or_secrets` | 異常 | 手元のパス・シークレットらしい文字列・NaN がない |
| 37 | `test_served_model_matches_adoption` | 正常 | `adopted` が真 ⇔ `MODEL_VERSION` が V2 ⇔ `models/cloud_base.joblib` の `model_version` が V2 で `metrics_improved.json` と同じ。偽・ファイルなしなら V1 |

- 期待値のもと：手で書いた小さな表（見て分かる値）、spec の上限（1,524）と 10%、この計画の表。**検証・テストの年の数値（MAE が何 m か、どの設定が選ばれるか）は、テストの期待値にしない**。
- テスト 32・33・37 は、結果によって確かめる中身が変わる。`skip` は使わず、ファイルの有無と `adopted` の値で分ける。
- `tests/app/` は変えない（`model_version` は、コミットしたファイルの値と形だけを見ている）。採る場合に通ることを確かめる。

## 実装の順（止まるところ）

1. `ml/` のテストと実装（テスト 1〜27）。
2. 07 をサンプルで通す → 全期間で 2 回実行する。
3. **ここで止まって、検証の結果と選ばれた設定を人間に報告する**（質問 3）。
4. 08 は、サンプルだけで作って通す。**全期間では 1 回だけ実行する**。08 に誤りが見つかって実行し直した場合は、回数と理由を dev-log に書く。
5. 結果を報告する。採る場合は「採る場合だけ行う変更」を行う。spec・model-card を書く。

## 追加する依存パッケージ

なし。

## セキュリティ上の注意

- 入力検証：エンドポイントは足さない（利用者の入力はない）。ノートブックの切り替えは `sample`／`full` 以外をエラーにする。学習・選ぶ関数は、行のずれ・不正な重みと閾値・欠けた表を拒否する。
- シークレット：使わない。`.env` は読まない。
- 外部通信（ホスト・タイムアウト）：なし。07・08 は保存済みの parquet とモデルのファイルだけを読む。全期間の実行は `Dockerfile.dev` のイメージの中で、`--network none` を付ける（v1 を作ったときと同じ。既存のイメージを使い、新しく取得するものはない。イメージがなければ、ビルドの前に伝える）。
- モデルのファイル（pickle）：読み込むのは、リポジトリの決まったパスだけ（`models/cloud_base.joblib`、`models/cloud_base_v2.joblib`、採った後の `models/cloud_base_v1.joblib`）。環境変数・入力からパスを作らない。`load` は、2 段階のファイルの中身（型・閾値の範囲・キー）も確かめる。
- API のイメージ：`models/` をそのまま入れている。採る場合、v1 のファイルもイメージに入る（約 0.45 MB。API は読まない）。
- reports：手元のパス・シークレットらしい文字列がないことをテストで確かめる。

## リスク・未決事項

- **テストの年を見るのは 2 回目**。今回採らなかった場合、次に改善を試すと 3 回目になる。`model-card.md` に回数を書く。
- **検証の年で 6 つから選ぶので、検証の数値は良く出やすい**。2024 年は 4 回目の使用。2 つの年の最も小さい値で選ぶことで弱めているが、なくならない。
- **重みと閾値の値に根拠がない**。3 段階のどれも基準 1 を満たさない・どれも足りない、がありうる。その場合も値を足さない（決まりの 4 で終わる）。
- **全体の MAE は悪くなる見込み**（v1 は全体の MAE を直接小さくしている。今回の設定は、上限より下の行のために全体を譲る）。どこまで悪くなるかは、実行するまで分からない。
- 重みを付けた設定は、木の数を決める指標も重み付きになる（v1 は重みなしの MAE）。
- **サンプル（fixture の 2 日ぶん）は、ベルリン 48 行がすべて上限より下、東京 47 行がすべて上限**（2026-10-13 に数えた）。2 つを合わせれば 2 段階のモデルは学習できるが、東京は基準 2 を判定できない。サンプルでは `selected` が `null` になりうるので、08 のサンプルの実行は、`selected` によらず最初の設定で動くようにする（動くことの確認だけ）。
- 全期間の実行を Docker の中で行うと、`current` の数値が `training.json` と同じになるはず（テスト 30）。違った場合は、止まって報告する（環境の違いか、`fit` の変更の誤り）。
- 学習と推論で入力が違う（再解析と予報）という限界は、そのまま残る。
- 範囲は 1 機能として大きい（テスト 37 件、ノートブック 2 つ）。分けるなら「07 まで（比較）」と「08 から（テストの年・採用）」の 2 つの PR。推奨は 1 つのまま（spec の #17 が 1 機能で、途中の状態では受け入れ条件を満たせない）。

## ブロッカー（人間の対応が必要なこと）

- なし（外部API の新しい項目・依存の追加はない）。
- Issue #27 の本文は読めていない（この PC に `gh` がない）。タイトル以外の要件があれば貼ってほしい。なければ、この計画のまま進める。ブランチは `feature/issues_27`。

## 質問

**回答（2026-10-13、人間）：「OKです」。1〜7 すべて推奨どおり。** 決まったこと：

- 1：D（重み 3 つ）と A（閾値 3 つ）の 6 設定。B と、D の「目的関数を変える」は試さない
- 2：重みは 2・4・8、閾値は 0.5・0.4・0.3
- 3：2023 年と 2024 年の 2 つで検証する。テストの年の前に一度止まって報告する
- 4：選んだ設定が検証で `current` より良くなければ、テストの年は評価しない。テストの年で 2 都市とも成功基準を満たしたときだけ採る
- 5：採る場合、v1 を `models/cloud_base_v1.joblib` に移し、04〜06 の読み書きの先を直す
- 6：07・08 と成果物 2 つを足す。spec のノートブックの表と CLAUDE.md の 1 行も直す
- 7：`model_version` は `<作った日>-lgbm-v2`
- Issue #27 の本文は貼られていないので、この計画のまま進める

1. **試す案**：D（重み 3 つ）と A（閾値 3 つ）の 6 設定でよいか。
   - B（概算式からのずれを学習）は入れない、を推奨。#16 で決めた根拠に当たると言い切れず、設定が増えるほど検証の年に合わせやすくなる。
   - D の「目的関数を変える」も試さない、を推奨（同じ理由）。
2. **重み 2・4・8 と閾値 0.5・0.4・0.3**：データ上の根拠はない。この値でよいか。変える場合は、いま（結果を見る前）に決めたい。
3. **検証は 2023 年と 2024 年の 2 つで順に行い、テストの年の前に一度止まって報告する**、でよいか。
   - 別案：2024 年だけ（学習は半分で済むが、2024 年に合わせやすい）。
4. **進む条件と採る条件**（「選ぶ決まり」の 4 と 6）でよいか。
   - 4：選んだ設定が、検証で `current` より良くなければ、テストの年は評価しない。
   - 6：テストの年で 2 都市とも成功基準を満たしたときだけ採る。推奨の理由：すでにある成功基準だけで決まり、新しい線を作らない。
   - 別案：成功基準に届かなくても、基準 1 を満たしたまま基準 2 が v1 より良ければ採る。この場合、API のモデルは「全体の MAE は v1 より悪いが、低いシーリングは良い」ものに替わる。
5. **採る場合のファイルの置き方**：v1 を `models/cloud_base_v1.joblib` に移し、04〜06 の読み書きの先を 1〜2 行ずつ直す（reports が変わらないことをハッシュで確かめる）、でよいか。
   - 別案：04・05 を新しい設定に書き換える（`training.json`・`metrics.json` が新しいモデルの値に置き換わり、v1 の数値のもとは git の履歴と `model-card.md` だけになる）。推奨しない。
6. **ノートブック 2 つ（07・08）と成果物 2 つ（`improvement.json`・`metrics_improved.json`）を足し、spec のノートブックの表と CLAUDE.md の「ディレクトリ」の 1 行を直してよいか**。
7. **`model_version`**：新しいモデルは `<作った日>-lgbm-v2`（今日なら `2026-10-13-lgbm-v2`）でよいか。

## 実装時の変更

**結果（2026-10-13）**：検証で選ばれたのは `two_stage_30`（点 0.1240。`current` は -0.1476）。人間の「テストの年へ進んで」の後、08 を全期間で 1 回実行した。テストの年で 2 都市とも成功基準を満たし（`adopted: true`）、決まりの 6 のとおり採った。「採る場合だけ行う変更」を行い、`model_version` は `2026-10-13-lgbm-v2`。

- **テストを 1 件足した**（37 件 → 38 件）：`test_improvement_report_selection_follows_the_rule`。計画のテスト 29 のうち、「`selection` と `selected` が、ファイルの中の判定と決まりに合っているか」を分けた。
- **既存のテストの名前**：`test_committed_model_matches_current_features_and_reports` は `test_v1_model_matches_current_features_and_reports` に変えた（見るファイルが v1 のファイルになったため）。
- **Red にならなかったテストが 4 件ある**。テスト 13（1 段階のファイルは 5 キー）は、いまの動作を守るテストなので最初から通る。テスト 33・34・35（`metrics_improved.json` の中身）は、ファイルがなければ何も確かめずに終わる作りなので、08 を全期間で実行するまでは通っていた。
- **2 段階の不正な組み合わせ**（分類のモデルと閾値の片方だけ、閾値が 0〜1 の外）は、`CloudBaseModel` を作るときに `ValueError`。`load` は、それを `ModelLoadError` にする。計画には、どこでエラーにするかを書いていなかった。
- **`select` の戻り値**：`{"selection": {設定: {"eligible", "score"}}, "selected": 名前 または None}`。点は、残らなかった設定にも出す（判定できない値が 1 つでもあれば `None`）。判定できない値のある設定は、残らない。`current` の点が `None` なら、選ばない。
- **`fit_below_cap`** は、正解が上限より下でない行を欠損にして `fit` を呼ぶだけにした（重みなし）。
- **`ROLLING_FOLDS`** は、名前 → （学習の年, 検証の年）の辞書。`fit_candidates` は、`current` に `MODEL_VERSION_V1`、ほかに `MODEL_VERSION_V2` を付ける。
- **手書きの表を作る関数**は、3 つのテストファイルにそれぞれ書いた（`tests/ml/tables.py` は計画のファイル一覧にないので変えていない）。
- **サンプルの実行**：07 は、東京の基準 2 を判定できないので `selected` が `None` になり、モデルを保存しない。08 は、07 の出力を読まず、その場で学習した `weighted_2` と `current` を使う（動くことの確認だけ）。
- **04 の変更は 3 か所**（計画では 2 行）：書く先、`CloudBaseModel` に `model_version=MODEL_VERSION_V1` を渡す、`training.json` に書く `model_version`。あわせて 04・05・06 の最初の説明の文のファイル名も直した（1 か所ずつ）。
- **05・06 が reports に書く説明の文字列**（`"LightGBM (models/cloud_base.joblib), clipped to [0, cap_m]"`）は、直していない（直すと `metrics.json`・`error_analysis.json` が変わる）。v1 のファイルの名前は、いまは `models/cloud_base_v1.joblib`。
- **サンプルで 05・06 が作るモデルの `model_version`** は、既定値なので v2 の文字列になる（一時的な場所にだけ書く。コミットする reports には関係しない）。
- **全期間の実行**は、`Dockerfile.dev` のイメージ（すでにあったもの。ビルドし直していない）の中で、`--network none` を付けて行った。
  - 07：2 回実行し、`reports/improvement.json` と候補のモデルのファイルは同じハッシュ。
  - 08：1 回。ファイルの置き方を変えた後に、04〜08 をもう 1 回まとめて実行した（08 は計 2 回。同じモデル・同じ設定で、`reports/metrics_improved.json` は同じハッシュ）。
  - 置き方を変えた後：2 つのモデルのファイルと、`improvement.json`・`metrics_improved.json`・`baseline.json` は、前と同じハッシュ。`training.json`・`metrics.json`・`error_analysis.json` は、**作業ツリーのファイルのハッシュは変わった（改行が CRLF から LF になった。この PC の git の `core.autocrlf` が `true` で、チェックアウトしたファイルは CRLF、Docker の中で書いたファイルは LF）。git が見る中身（`git hash-object`）はコミット済みのものと同じで、`git diff` は空**。
- **08 の未使用の import**（`train`）を、全期間の実行の後に消した（ruff の指摘）。消した後は、サンプルでだけ実行した（全期間では実行し直していない。出力に関係しない行）。
- **API の確認**：`docker build` したイメージ（631 MB）を起動し、`/cloud-base` を東京・ベルリンで 1 回ずつ呼んだ（Open-Meteo への通信が 2 回）。`model_version` は `2026-10-13-lgbm-v2`。`tests/app/` は変更なしで通った。
- **分類の木の数が 2 つの検証の年で同じ（172 本）** だったので、別に学習し直して確かめた（どちらも 172 本。検証の対数損失は違う値）。
- **`/review` の後の修正（2026-10-13、人間が「推奨で修正して」と指定。🟡 の 5 件を対象にした。🟢 の 5 件は直していない）**：
  - 05・06 が reports に書く説明の文字列を `models/cloud_base_v1.joblib` に直し、05・06 を全期間で実行し直した。`reports/metrics.json`・`reports/error_analysis.json` は、この 1 行ずつだけが変わった（数値は同じ。上の「直していない」は、この修正の前の状態）。05 は v1 をテストの年でもう一度評価している（同じモデルで、数値は同じ）。
  - 05・06 のサンプルの分岐で作るモデルに、`MODEL_VERSION_V1` を渡すようにした。
  - `Dockerfile.dev` のイメージの中（`--network none`）で、01〜08 をサンプルで実行して通った。
  - 08 は、全期間では実行し直していない（未使用の import を消す前のノートブックで作った `metrics_improved.json` のまま）。
  - 実装をわざと壊す確認を 7 通り行った：`predict_m` の `>=` を `>` に、`select` の「`current` 以下なら選ばない」を「未満」に、検証の側の重みを外す、学習の側の重みを外す、`select` が基準 1 を見ない、`adopt` を「どれか 1 都市」に、`load` が閾値の型を見ない。**検証の側の重みを外す変更だけ、テストが検出しなかった**。`test_fit_weights_the_validation_error_too` を足し（合計 39 件）、7 通りすべてを検出することを確かめた。このテストは、実装がすでにある状態で足したので、Red は「わざと壊したときに失敗する」で確かめた。
- 最終結果（レビュー後の修正の後は pytest 1,291 件。ほかは同じ）：pytest 1,290 件成功、カバレッジ 99.54%（`ml/improve.py`・`ml/model.py`・`ml/train.py`・`ml/split.py` は 100%）、ruff・mypy 問題なし、nbmake 8 件（サンプル）。
