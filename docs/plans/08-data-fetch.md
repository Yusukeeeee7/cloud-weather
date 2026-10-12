# 計画：#8 データ取得（Issue #15）

状態：承認済み（ブロッカー 1・2 は調査中。fixture の取得と実装は、調査結果への同意の後）

## 目的と受け入れ条件

spec.md「14. 機能一覧」より：

> | 8 | データ取得 | `01_data_fetch` で両都市のデータを取得・結合できる |

spec.md「9. 雲底高度予測（ML）」より：

> | `01_data_fetch.ipynb` | METAR・Open-Meteo の取得と時刻結合 | `data/processed/*.parquet` |
>
> - 目的変数：METAR の最も低い BKN または OVC 層の高さ（シーリング）をメートルに変換した値。
> - **シーリングなし（雲が少ない・ない）の扱いは EDA で決める**。
> - 時系列分割：学習 2018〜2023、検証 2024、テスト 2025（データ量を見て調整）。
> - 予測時点より後の情報を特徴量に使わない。

spec.md「7. 外部API・データ」より（どちらも **未確認**。ブロッカー 1・2）：

> | 過去の気象 | Open-Meteo Historical | `archive-api.open-meteo.com/v1/archive` … | 一部確認済み（sunrise・sunset だけ） |
> | METAR過去データ | Iowa Environmental Mesonet | ASOS/METAR ダウンロード、雲量（skyc1〜4）・雲高（skyl1〜4、フィート） | 要確認 | 未確認 |

関連する要件：

- CLAUDE.md「ノートブック」：上から再実行すれば同じ結果。成果物は `data/processed/` に保存。`02_eda` 以外は出力を消してコミットする（nbstripout）。
- CLAUDE.md「コーディング規約」：外部APIの呼び出しは `app/clients/` に集約し、タイムアウトを必ず指定。時刻は UTC。単位はメートル・摂氏（METAR の雲高はフィートなので変換する）。テストで外部APIを実際に呼ばない。
- spec 10：`data/` は git に入れず、`01_data_fetch` で再取得できる。
- spec 12：ノートブックは nbmake で小さなサンプルデータを使って実行確認。
- spec 13：nbmake は最初のノートブック（#8）で `ci.yml` に追加する。
- #1 からの申し送り：pandas などが Python 3.14 で入るかを #8 の計画時に確かめる（下の「追加する依存パッケージ」）。

完了の確認方法：

1. `uv run pytest --cov=app --cov=ml` が通る（カバレッジ 80% 以上）
2. `uv run ruff check . && uv run ruff format --check .`、`uv run mypy app ml` が通る
3. `uv run pytest --nbmake notebooks/` が、サンプルデータで、外部と通信せずに通る
4. 手動で 1 回、`01_data_fetch.ipynb` を本番の設定（全期間）で上から実行し、`data/processed/observations.parquet` ができる。行数・期間・都市ごとの件数・欠損の数を記録する
5. もう一度上から実行して、外部APIを呼ばずに（保存済みの生データから）同じ内容のファイルができる
6. PR で CI（nbmake を含む）が通る

## 今回やらないこと

- EDA（欠損・分布の分析、シーリングなしの扱いの決定）→ #9
- 特徴量作成（`ml/features.py`）、ベースライン、評価関数 → #10 以降
- 学習・検証・テストへの分割（今回は全期間を 1 つのファイルにするだけ）
- `/cloud-base` の API、推論時のデータ取得（予報のAPI から特徴量を作る部分）→ #12
- 東京・ベルリン以外の地点
- データの定期的な更新（今回は手動で 1 回取得できればよい）
- `data/` を git やクラウドに置くこと（spec 10：git に入れない）

## 変更・追加するファイル

| ファイル | 内容 |
|---|---|
| `app/clients/iem.py`（新規） | Iowa Environmental Mesonet から METAR の過去データを取得する。入力は `City`（→ ICAO は `app/cities.py` から）と年。出力は応答の本文（文字列）のまま。タイムアウト必須、リトライは #6 と同じ決まり。**パラメータ名・項目名はブロッカー 1 の確認後に書く** |
| `app/clients/open_meteo_archive.py`（新規） | Open-Meteo の過去データのAPIから、1 時間ごとの気象を取得する。入力は `City` と年。出力は応答の JSON のまま。**項目名はブロッカー 2 の確認後に書く** |
| `app/cities.py` | `CityInfo` に ICAO コード（`RJTT`・`EDDB`。spec 3 の値）を足す |
| `app/config.py` | 追加する設定（質問 6）：2 つのAPIの接続先、一括取得用のタイムアウト |
| `ml/metar.py`（新規） | IEM の応答（文字列）を表（pandas）にする。時刻を UTC に、雲高をフィート → メートルに、欠損の表記を欠損値に。雲の層（量・高さ × 4）から `ceiling_m`（最も低い BKN または OVC の高さ。なければ欠損）を作る |
| `ml/archive.py`（新規） | Open-Meteo の過去データの応答（JSON）を表にする。時刻を UTC に、列名を単位つきの名前に |
| `ml/dataset.py`（新規） | 2 つの表を時刻で結合する（質問 3）。都市の列を付け、両都市を 1 つの表にする。保存前に形（列・型・重複なし・時刻の順）を確かめる |
| `ml/raw_store.py`（新規） | 生データの置き場所（`data/raw/<提供元>/<city>_<年>.<拡張子>`）の読み書き。あれば読み、なければ取得して保存する（再実行で外部APIを呼ばないため） |
| `notebooks/01_data_fetch.ipynb`（新規） | 上の関数を順に呼ぶだけの薄いノートブック：設定 → 取得（または保存済みを読む）→ 整形 → 結合 → 確認の表示 → 保存。出力は消してコミットする |
| `tests/ml/test_metar.py`・`test_archive.py`・`test_dataset.py`・`test_raw_store.py`（新規） | 下のテスト 1〜26 |
| `tests/app/test_iem_client.py`・`test_open_meteo_archive_client.py`（新規）、`test_config.py` | 下のテスト 27〜36 |
| `tests/fixtures/iem/`・`tests/fixtures/open_meteo/archive_*`（新規） | 両都市の短い期間の実レスポンス（加工しない）。ノートブックのサンプルデータも兼ねる（質問 5）。`README.md` に取得日時・方法を追記 |
| `pyproject.toml`、`uv.lock` | 依存の追加（下の表）。依存グループの設定 |
| `.github/workflows/ci.yml` | nbmake のステップと、ノートブックに出力が残っていないことの確認を足す |
| `.gitignore` | `data/` は登録済み。変更は不要の見込み（確認だけ） |
| `docs/spec.md` | 質問の回答で決まった仕様、外部API表の状態、成果物の列の一覧、機能一覧 #8 の状態。**人間の回答にある内容だけを書く** |
| `.env.example` | 追加する変数の名前だけ。**AI は書けないので人間に依頼**（ブロッカー 4） |

設計の要点：

- **ノートブックは薄くする**。取得・整形・結合の中身は `.py` に書いて TDD で進める。ノートブックは nbmake で「上から実行して通る」ことだけを確かめる。
- **通信するコードは `app/clients/`、表にするコードは `ml/`**。クライアントは pandas を使わず、応答をそのまま返す（API のイメージに pandas を入れなくて済む）。
- **取得の単位は 都市 × 年**。期間は spec 9 の分割に合わせて 2018-01-01〜2025-12-31（質問 1）。2 都市 × 8 年 × 2 つのAPI ＝ **32 回** の外部呼び出し。
- **生データを `data/raw/` に保存し、あれば使う**。再実行で外部APIを呼ばない。取り直したいときは、そのファイルを人間が消す（ノートブックから消す操作はしない）。
- **時刻はすべて UTC**。どちらのAPIにも UTC で返すよう指定する（指定のしかたはブロッカー 1・2 で確認）。
- **結合**（質問 3）：1 行 ＝ 都市 × 正時（1 時間ごと）。その正時の気象（Open-Meteo）に、その正時に最も近い METAR（前後 30 分以内）を付ける。METAR がない正時も行は残し、METAR の列を欠損にする（捨てるかどうかは #9 で決める）。
- **`ceiling_m`**（質問 4）：spec 9 の定義どおり、最も低い BKN または OVC の層の高さ（m）。該当する層がなければ欠損。雲の層の列（量と高さ）も、メートルに直して残す（#9 の EDA で使う）。
- **成果物**：`data/processed/observations.parquet`（質問 2）。列の一覧は、ブロッカー 1・2 の確認後に決めて spec に書く。
- **サンプルで動かす仕組み**（質問 5）：ノートブックは環境変数で「サンプル／本番」を切り替える。サンプルでは `tests/fixtures/` の実レスポンスを生データとして読み、外部と通信せず、出力は一時的な場所に書く（`data/` を上書きしない）。既定はサンプル。
- **乱数は使わない**（取得と結合だけ）。行の順は 都市 → 時刻 で固定する。

### 確認が必要な項目（記憶で確定させない）

| 項目 | 確かめ方 |
|---|---|
| IEM のダウンロードのURL・パラメータ名・列名・欠損の表記・時刻の形式・タイムゾーンの指定・利用条件と呼び出しの制限 | **ブロッカー 1** |
| Open-Meteo の過去データのAPIの 1 時間ごとの項目名（気温・露点・湿度・気圧・風・雲量など）、1 回で取れる期間、呼び出しの数え方、データの出どころ（再解析）と遅れ | **ブロッカー 2** |
| 追加する依存が Python 3.14 で入るか | **計画の作成中に確認済み**：`uv pip install --dry-run` で pandas 3.0.6・pyarrow 26.0.0・pandas-stubs・nbmake 1.5.5・nbstripout 0.9.1・ipykernel 7.4.0 が解決できた（インストールはしていない。実際に動くかは実装時に確かめる） |
| uv の依存グループを、既定でインストールされるようにする書き方 | 実行して確かめる |
| nbmake の使い方（環境変数の渡し方、タイムアウト、カーネルの指定） | 実行して確かめる |
| nbstripout で「出力が残っていないこと」を確かめるコマンド | 実行して確かめる |
| pandas 3 の動き（時刻の列の型、文字列の型、parquet の読み書きで型が保たれるか） | 実行して確かめる |
| mypy（strict）が pandas のコードで通るか（`pandas-stubs` で足りるか） | 実行して確かめる |
| 1 年ぶんの取得にかかる時間と大きさ | 1 回取得して測る（タイムアウトの値を決める材料。質問 6） |

## テスト一覧（先に書く順）

| # | テスト名 | 種類（正常/異常/境界） | 確かめること |
|---|---|---|---|
| 1 | `test_parse_metar_columns_and_types` | 正常 | fixture（実レスポンス）を表にすると、決めた列・型になる。時刻は UTC |
| 2 | `test_parse_metar_converts_feet_to_meters` | 正常 | 雲高がメートル（fixture のフィートの値 × 0.3048。0.3048 は定義値） |
| 3 | `test_parse_metar_missing_values` | 境界 | 欠損の表記が欠損値になる（文字列のまま残らない、0 にならない） |
| 4 | `test_ceiling_is_lowest_bkn_or_ovc` | 正常 | 層の組み合わせ（FEW→BKN→OVC など）で、最も低い BKN/OVC の高さになる。入力は手で書いた小さな表 |
| 5 | `test_ceiling_is_missing_without_bkn_or_ovc` | 境界 | 快晴・FEW・SCT だけのとき欠損 |
| 6 | `test_ceiling_ignores_layers_without_height` | 境界 | 量はあるが高さが欠損の層の扱い（質問 4） |
| 7 | `test_ceiling_matches_fixture_rows` | 正常 | fixture の数行について、層の列と `ceiling_m` が合う（期待値は fixture の値から） |
| 8 | `test_parse_metar_rejects_unexpected_format` | 異常 | 列が足りない・空・HTML のエラーページなどは、黙って空の表にせずエラー |
| 9 | `test_parse_metar_drops_exact_duplicates` | 境界 | 同じ時刻の同じ報告が 2 行あれば 1 行にする |
| 10 | `test_parse_metar_is_sorted_by_time` | 正常 | 時刻の昇順 |
| 11 | `test_parse_archive_columns_and_types` | 正常 | fixture を表にすると、決めた列・型。時刻は UTC |
| 12 | `test_parse_archive_keeps_units` | 正常 | 応答の単位（℃、m/s、hPa など）が想定と違えばエラー（単位を黙って取り違えない） |
| 13 | `test_parse_archive_missing_values` | 境界 | null は欠損値 |
| 14 | `test_parse_archive_rejects_unexpected_format` | 異常 | 項目が欠けている・配列の長さが違う・`error` を含む応答はエラー |
| 15 | `test_join_one_row_per_city_hour` | 正常 | 結合後は 都市 × 正時 で重複なし。行数は気象の行数と同じ |
| 16 | `test_join_picks_nearest_metar_within_30_minutes` | 正常 | 正時に最も近い METAR が付く。入力は手で書いた小さな表 |
| 17 | `test_join_boundary_30_minutes` | 境界 | ちょうど 30 分、30 分 1 秒、同じ距離が 2 つあるとき（質問 3） |
| 18 | `test_join_keeps_hours_without_metar` | 境界 | METAR のない正時も行が残り、METAR の列は欠損 |
| 19 | `test_join_does_not_mix_cities` | 異常 | 東京の METAR がベルリンの行に付かない |
| 20 | `test_join_records_metar_time` | 正常 | 付けた METAR の観測時刻が列に残る（ずれを後で確かめられる） |
| 21 | `test_join_rejects_naive_or_non_utc_times` | 異常 | タイムゾーンのない時刻の表はエラー |
| 22 | `test_dataset_is_deterministic` | 正常 | 同じ入力から 2 回作ると同じ表（行の順も） |
| 23 | `test_dataset_roundtrips_through_parquet` | 正常 | 保存して読み直すと、列・型・値が同じ |
| 24 | `test_raw_store_reads_existing_file_without_fetching` | 正常 | 生データがあれば取得の関数を呼ばない |
| 25 | `test_raw_store_fetches_and_saves_when_missing` | 正常 | なければ 1 回取得して保存し、2 回目は読むだけ |
| 26 | `test_raw_store_does_not_save_failed_fetch` | 異常 | 取得が失敗したら、空や途中のファイルを残さない |
| 27 | `test_iem_client_requests_expected_parameters` | 正常 | 送るURL・パラメータが確認済みのもの（`respx`）。観測所は ICAO、期間は年の初めから終わり、UTC |
| 28 | `test_iem_client_station_comes_from_allowlist` | 異常 | 観測所のコードは `City` からだけ決まる（文字列を受け取らない） |
| 29 | `test_iem_client_timeout_and_5xx_are_retried` | 異常 | #6 と同じ決まり（最大 2 回、4xx はリトライしない） |
| 30 | `test_iem_client_failure_raises_upstream_error` | 異常 | 使い切ったら `UpstreamError`。文面にURLを含まない |
| 31 | `test_archive_client_requests_expected_parameters` | 正常 | 送るURL・パラメータが確認済みのもの |
| 32 | `test_archive_client_timeout_and_5xx_are_retried` | 異常 | 同上 |
| 33 | `test_archive_client_error_body_raises` | 異常 | 200 でも `error` を含む応答・JSON でない応答は `UpstreamError` |
| 34 | `test_clients_use_configured_timeouts` | 境界 | 設定のタイムアウトが通信に渡っている（直書きでない） |
| 35 | `test_settings_data_fetch_defaults_and_validation` | 異常/境界 | 追加する設定の既定値と範囲 |
| 36 | `test_cities_have_icao` | 正常 | `tokyo` → `RJTT`、`berlin` → `EDDB`（spec 3） |
| 37 | `notebooks/01_data_fetch.ipynb`（nbmake） | 正常 | サンプルの設定で上から最後まで実行でき、外部と通信しない |
| 38 | `test_notebook_has_no_outputs` | 正常 | コミットするノートブックに出力・実行番号が残っていない |

- すべて `respx` でモックするか、fixture・手で書いた小さな表を使う。テストから外部APIを呼ばない。
- 期待値は、fixture の値、定義値（1 フィート ＝ 0.3048 m）、手で書いた入力から読み取れるものだけ。
- Red の確認：`ml/`（1〜26）→ クライアント・設定（27〜36）→ ノートブック（37・38）の順。骨組みでも通るテストは一覧にして、何も確かめていないものがないか見る（#7 の再発防止）。
- **ブロッカー 1・2 が解けないあいだは、fixture を取得できず、1〜3・7・11〜14・27・31 を書けない**。skip で置いたり、AI が作った応答で埋めたりはしない。

## 追加する依存パッケージ

| パッケージ | 入れる場所 | 理由 | 代替案 |
|---|---|---|---|
| `pandas` | 新しい依存グループ `ml` | 表の整形・結合（CLAUDE.md の技術スタック） | 標準ライブラリの `csv` だけで書く：結合と欠損の扱いを自分で書くことになり、#9 以降は結局 pandas が要る |
| `pyarrow` | `ml` | parquet の読み書き（spec の成果物が `*.parquet`） | `fastparquet`：pandas の既定は pyarrow。CSV で保存：spec と違い、型が保たれない |
| `nbmake` | `dev` | ノートブックの実行確認（spec 12・13） | `jupyter nbconvert --execute`：pytest と別の仕組みになる |
| `ipykernel` | `dev` | nbmake がノートブックを実行するためのカーネル | なし（必要） |
| `nbstripout` | `dev` | 出力を消してコミットする（CLAUDE.md） | 自分で JSON を見るテストを書く（テスト 38 はこの形。nbstripout は消す道具として使う） |
| `pandas-stubs` | `dev` | `uv run mypy ml`（strict）を通すための型の情報 | mypy で pandas を無視する設定：型の間違いを見逃す |

- `ml` グループは API のイメージ（`UV_NO_DEV=1`）には **入れない**。#12（推論API）で必要になったら本体の依存へ移す。CI と手元では `ml` も既定で入るようにする。
- LightGBM・Jupyter の画面（`jupyterlab`／`notebook`）は今回入れない（学習は #11。ノートブックの編集は VS Code などの手元の道具で行う前提。質問 8）。
- いっしょに入る間接の依存は、`dry-run` の結果で 37 個（numpy、ipython、jupyter-client、pyzmq、tornado など）。CI の `pip-audit` の対象になる。

## セキュリティ上の注意

- 入力検証：利用者の入力はない（API のエンドポイントは足さない）。都市は `City`（許可リスト）、年は整数で範囲を確かめる。観測所のコード・緯度・経度は `app/cities.py` の値だけを使う。
- シークレット：どちらのAPIもキー不要の見込み（ブロッカー 1・2 で確認）。`.env` は読まない。
- 外部通信（ホスト・タイムアウト）：
  - 通信先は `archive-api.open-meteo.com`（spec の表にある）と、IEM のホスト（**spec の表にホスト名がない。ブロッカー 1 で確認して表に書く**）。URL は設定の接続先とコードの中の決まったパスから作り、入力から組み立てない。
  - タイムアウトは必ず指定する。1 年ぶんの一括取得は、spec の「全体 10 秒」に収まらない可能性がある（質問 6）。
  - **まとめて 32 回呼ぶ**。続けて呼ぶときは 1 回ずつ順に行い、並列にしない。リトライは最大 2 回、4xx（429 を含む）はリトライしない。呼びすぎを避けるため、取得済みの年は呼ばない。
- 取得したデータの扱い：応答はそのまま信用せず、列・型・単位を確かめてから表にする（想定と違えばエラー）。保存するファイル名は `City` と年から作る（応答の内容からパスを作らない）。
- ノートブック：出力を消してコミットする（出力に、パスや環境の情報が残らないように）。CI のサンプル実行は外部と通信しない。
- データの利用条件：Open-Meteo は CC BY 4.0・非商用。IEM は未確認（ブロッカー 1）。`data/` は git に入れないが、**fixture（短い期間の実レスポンス）は git に入る** ので、再配布してよいかを確かめる。
- 依存：6 つ追加（間接を含めて 37）。`pip-audit` を実装時に手元でも実行する（#7 では実行が後になった）。

## 実行のたびに枠を使うものの見積もり

- 外部API：本番の取得で **32 回**（IEM 16、Open-Meteo の過去データ 16）。fixture の取得で **4 回**（2 都市 × 2 つのAPI、短い期間）。ブロッカー 1・2 の確認で **数回**（AI が確認する場合。実際に呼んだ回数を数えて記録する）。テスト・CI からは 0 回。
  - Open-Meteo は、期間の長い要求を複数回ぶんとして数える可能性がある（未確認。ブロッカー 2）。上限は 10,000 回/日。
- GitHub Actions：PR の作成で 1 回、レビュー後の修正と dev-log をまとめて 1 回の **計 2 回** を目安。nbmake のぶん、1 回の時間は延びる（どのくらいかは未計測）。

## リスク・未決事項

- **外部APIの項目が未確認**（ブロッカー 1・2）。確認の結果によって、列の一覧・テスト・取得の単位（年ごとでよいか）が変わる。
- **2 つのデータの時刻の意味が違う可能性**：METAR は観測した瞬間、Open-Meteo の 1 時間ごとの値は項目によって「その時刻の値」と「前の 1 時間の合計・平均」がある（未確認。ブロッカー 2）。結合の決まりは、確認後に見直すことがある。
- **METAR の報告の間隔・時刻は空港で違う**（毎時 0 分・30 分とは限らない）。「前後 30 分以内で最も近い」で足りるかは、取得したデータを見て確かめる。
- **METAR の雲の表し方**：spec は BKN・OVC だけをシーリングとしている。ほかの表し方（鉛直視程など）が IEM の列にどう入るかは未確認。見つけたら #9 への申し送りにする。
- **学習（過去データ）と推論（予報）でデータの出どころが違う**（spec 9 のとおり、#11 で `model-card.md` に書く）。今回は、過去データの項目を、予報のAPIで使える項目に合わせて選ぶ。
- **データが大きい・取得が遅い場合**：1 年ぶんの大きさと時間は測っていない。年ごとで大きすぎれば、月ごとに分ける（呼び出しが増える）。
- **依存が Python 3.14 で実際に動くか**：解決できることは確かめたが、インストールして動かしてはいない。
- **pandas 3 は新しい**。記憶にある書き方が変わっている可能性があるので、使う関数は実行して確かめる。
- **Docker のイメージ**：`ml/` はイメージにコピーされるが、pandas は入らない。API が `ml/metar.py` などを import しない限り問題ない（今回は import しない）。
- **Windows の手元環境**：ノートブックの実行（カーネルの起動）がアプリケーション制御ポリシーで止められる可能性がある（`uv run uvicorn` で起きた）。その場合は Docker か CI で確かめる。
- **Issue #15 の本文を読めていない**（`gh` がこの環境にない）。spec の機能 #8 と同じ内容という前提。
- **範囲が大きい**（クライアント 2 つ、整形 2 つ、結合、ノートブック、CI、依存）。分割は質問 9。

## ブロッカー（人間の対応が必要なこと）

それぞれ推奨を 1 つ書いています。「推奨で」と返してもらえれば、その内容で進めます。

1. **IEM（METAR の過去データ）の確認**（spec の表で未確認）。
   - 推奨：**#4・#7 と同じく、AI が公式ドキュメントと実レスポンスを照合して報告し、同意をもらってから fixture を取得する**。確認するのは、ホストとURL、パラメータ名、列名（雲量・雲高・気温・露点など）、欠損の表記、時刻とタイムゾーン、利用条件、呼び出しの制限、fixture を git に入れてよいか。
2. **Open-Meteo の過去データのAPIの、1 時間ごとの気象の項目の確認**（spec の表では sunrise・sunset だけ確認済み）。
   - 推奨：**同じく AI が公式ドキュメントと実レスポンスを照合して報告する**。確認するのは、項目名、単位の指定、各項目の時刻の意味、1 回で取れる期間と呼び出しの数え方、データの出どころと遅れ。
3. **依存パッケージ 6 つの追加の承認**（上の表）。
   - 推奨：**表のとおり追加する**（`ml` グループに pandas・pyarrow、`dev` に nbmake・ipykernel・nbstripout・pandas-stubs）。
4. **`.env.example` への追記**（実装後。AI は書けない）。追記する変数名は、質問 6 の回答で決まったものを実装時に渡します。
5. **Issue #15 の本文**：spec の機能 #8 にない要件が書かれていれば教えてください。なければ、spec と同じ内容として進めます。

### ブロッカー 1・2 の調査結果（2026-10-12、AI が公式ドキュメントと実レスポンスを照合）

状態：**人間の同意待ち**（下の「決めてほしいこと」）。同意をもらうまでブランチを作らず、fixture の保存も実装もしない。

**1. IEM（METAR の過去データ）**

| 確認したもの | 場所 | 分かったこと |
|---|---|---|
| API の説明 | `mesonet.agron.iastate.edu/cgi-bin/request/asos.py?help` | GET。パラメータ：`station`、`data`（列。複数可）、`sts`・`ets`（開始・終了の時刻）、`tz`（IANA の名前。`UTC` など）、`format`（既定 `onlycomma`）、`missing`（既定 `M`。ほかに `null`・`empty`）、`trace`（既定 `0.0001`。ほかに `null`・`empty`）、`report_type`（1＝HFMETAR、3＝Routine、4＝Specials。既定はすべて）。**制限：同じ IP からは 1 秒に 1 回まで（超えると 429。2026-04-21 から）、混雑時は 503、1 回の要求は 1,000 観測所・年まで（超えると 422）** |
| 列の説明 | `mesonet.agron.iastate.edu/request/download.phtml` | `valid`＝観測の時刻、`tmpf`・`dwpf`＝気温・露点（華氏）、`relh`＝湿度（%）、`sknt`＝風速（ノット）、`alti`＝高度計の気圧（インチ）、`mslp`＝海面気圧（ミリバール）、`vsby`＝視程（マイル）、`skyc1〜4`＝雲の層の量、`skyl1〜4`＝雲の層の高さ（フィート）、`wxcodes`＝天気の記号、`metar`＝もとの電文。期間は開始を含み、終了を含まない。「迷ったら routine と specials の両方を選ぶ」と書かれている |
| 利用条件 | `mesonet.agron.iastate.edu/disclaimer.php` | 「このサイトの資料はパブリックドメインで、合法な目的なら誰でも自由に使える」「IEM（アイオワ州立大学）と書いてもらえるとありがたい」。正確さの保証はない。ページの下には「All rights reserved」の表示もある（2 つの関係は書かれていない） |
| 実レスポンス | 2 回（RJTT・EDDB、2025-01-15〜16 の 2 日ぶん、UTC） | どちらも 200（1.0 秒・0.5 秒、18 KB・14 KB）。1 行目が列名、時刻は `2025-01-15 00:00` の形。**RJTT は毎時 0 分・30 分と臨時の報告（01:48 など）、EDDB は毎時 20 分・50 分**。`mslp` は 2 都市とも空。`missing=empty` で欠損は空文字 |

- **高さのない雲の層が実際にある**：RJTT の電文 `FEW030 SCT///` は、`skyc2=SCT`・`skyl2` が空で入っていた（質問 4 の「高さが欠損の層は飛ばす」が実際に使われる）。
- EDDB の報告は `AUTO`（自動観測）。雲がないときの表し方（`NCD` など）や鉛直視程（`VV`）が列にどう入るかは、2 日ぶんでは出てこなかった（#9 への申し送り）。
- 華氏・マイル・フィートで返るので、摂氏・メートルに直す（CLAUDE.md の単位の決まり）。

**2. Open-Meteo の過去データのAPI（1 時間ごと）**

| 確認したもの | 場所 | 分かったこと |
|---|---|---|
| 項目の説明 | `open-meteo.com/en/docs/historical-weather-api` | `hourly=` に temperature_2m、dew_point_2m、relative_humidity_2m、pressure_msl、precipitation、weather_code、cloud_cover、cloud_cover_low/mid/high、wind_speed_10m がある。**precipitation だけ「前の 1 時間の合計」、ほかは「その時刻の値」**。`wind_speed_unit=ms`、`timeformat=unixtime`、`timezone` の既定は GMT。データは ERA5（約 25 km、1940 年〜、5 日遅れ）・ERA5-Land・ECMWF IFS（9 km、2017 年〜）などの再解析で、既定ではそれらを組み合わせる |
| 呼び出しの数え方 | `open-meteo.com/en/pricing` | 「10 項目を超える」「1 地点で 2 週間を超える」要求は複数回ぶんとして数える（小数で数える。例：2 週間・15 項目＝1.5 回）。式は書かれていない。無料の上限は 600 回/分・5,000 回/時・10,000 回/日・300,000 回/月 |
| 実レスポンス | 1 回（ベルリン、2025-01-15〜16、上の 11 項目） | 200（0.2 秒、3 KB）。48 行、列ごとの配列、時刻は UNIX 秒で正時。単位は `°C`・`%`・`hPa`・`mm`・`wmo code`・`m/s`。応答の座標は 52.337433, 13.5（送った値は 52.36, 13.50） |

- 1 年・11 項目の要求は、例から考えると 1 回で 30 回ぶん前後に数えられる（**AI の推定。式は公式に書かれていない**）。16 回の要求で 500 回ぶん前後。上限（5,000 回/時）には収まる見込み。
- 予報のAPI（推論で使う）と同じ項目名がそろっている。`pressure_msl` も過去データにあった（予報のAPI側の確認は #12）。

**外部への通信（この調査で行ったもの）**：IEM のAPI 2 回、Open-Meteo の過去データのAPI 1 回、ドキュメントのページ 5 回（IEM 3、Open-Meteo 2）。

**計画から変わる点**

- IEM は 1 秒に 1 回の制限があるので、続けて呼ぶときは **間を 2 秒あける**（#6 の `wait` と同じく、テストでは実際に待たない）。429 は #6 の決まりどおりリトライしない（その年で止まる。取得済みの年は保存してあるので、やり直すと続きから進む）。
- METAR の気圧（`mslp`）は 2 都市とも入っていない。気圧は Open-Meteo の `pressure_msl` を使う。
- 単位の変換が増える：華氏 → 摂氏、マイル → メートル、フィート → メートル。

**決めてほしいこと（推奨）**

- A. **IEM の呼び方**：`station`（ICAO）、`sts`・`ets`（年の初め〜翌年の初め、UTC）、`tz=UTC`、`format=onlycomma`、`missing=empty`、`trace=empty`、`report_type=3` と `4`（定時と臨時）。
- B. **IEM から取る列**：`tmpf`・`dwpf`・`vsby`・`skyc1〜4`・`skyl1〜4`・`wxcodes`・`metar`（もとの電文を残しておけば、ほかの値が要るときに取り直さずに済む）。風・湿度・気圧は取らない（特徴量は、推論でも使える Open-Meteo の値から作るため）。
- C. **Open-Meteo の過去データの呼び方**：上の 11 項目、`wind_speed_unit=ms`、`timeformat=unixtime`、`timezone` は指定しない（GMT）。`start_date`・`end_date` は年の初め〜終わり。
- D. **IEM の呼び出しの間隔**：2 秒あける。並列にしない。
- E. **fixture**：調査で取得した 3 つの応答（RJTT・EDDB の METAR、ベルリンの気象。2025-01-15〜16）をそのまま fixture にし、足りない 1 つ（東京の気象）だけを追加で取得する（取り直さないので、外部APIは 1 回で済む）。IEM の利用条件はパブリックドメインなので、git に入れる。
- F. **出典の表示**：`tests/fixtures/README.md` と（#11 の）`model-card.md` に、Open-Meteo（CC BY 4.0）と IEM（アイオワ州立大学）を書く。
- G. **spec の表**：IEM のホスト・項目・制限と、過去データのAPIの項目を、実装ブランチで「7. 外部API・データ」に書き、状態を確認済みにする。

## 質問

### 回答（2026-10-12 人間）

- 「進めてください」。計画を承認。質問 1〜9 とブロッカー 1〜3・5 は **すべて推奨どおり** と解釈した（AI の解釈。計画の要約に「『推奨で』と返してもらえれば進められる」と書いたうえでの回答）。
  - ブロッカー 1・2：AI が公式ドキュメントと実レスポンスを照合して報告し、同意をもらってから fixture を取得する。
  - ブロッカー 3：依存 6 つを表のとおり追加する。
  - ブロッカー 5：Issue #15 に追加の要件の連絡なし。spec の機能 #8 と同じ内容として進める。

### 質問の内容

それぞれ推奨を 1 つ書いています。

1. **取得する期間**：推奨は **2018-01-01〜2025-12-31（UTC）**。spec 9 の分割（学習 2018〜2023、検証 2024、テスト 2025）のとおり。
2. **成果物の名前と形**：推奨は **`data/processed/observations.parquet` の 1 ファイル**（両都市、`city` の列で区別。1 行 ＝ 都市 × 正時）。
3. **結合の決まり**：推奨は **正時ごとに、前後 30 分以内で最も近い METAR を 1 つ付ける**。同じ距離が 2 つあるときは **前（正時より早いほう）** を取る。ちょうど 30 分は含める。METAR のない正時は行を残して欠損にする。付けた METAR の観測時刻を列に残す。
4. **`ceiling_m` を #8 で作るか**：推奨は **作る**（spec 9 の定義どおり、最も低い BKN または OVC の高さ。なければ欠損。「なし」をどう扱うかは #9 で決める）。量が BKN/OVC でも高さが欠損の層は、**その層を飛ばして次の層を見る**。雲の層の列もメートルに直して残す。
5. **ノートブックをサンプルで動かす仕組み**：推奨は **環境変数 `DATA_FETCH_MODE`（`sample`／`full`）で切り替え、既定は `sample`**。`sample` は `tests/fixtures/` の実レスポンスを読み、外部と通信せず、一時的な場所に書く。全期間の取得は、`full` を明示したときだけ行う（うっかり 32 回呼ばないため）。
6. **一括取得のタイムアウトと設定の名前**：spec は「接続 3 秒、全体 10 秒」ですが、1 年ぶんの取得は 10 秒に収まらない可能性があります。推奨は **一括取得用に別の設定を持つ**：`DATA_FETCH_TIMEOUT_S`（既定 60。接続は 3 秒のまま、リトライは最大 2 回のまま）、接続先は `IEM_BASE_URL`・`OPEN_METEO_ARCHIVE_BASE_URL`。60 秒で足りるかは 1 回取得して測り、足りなければ報告します。spec 7 に書き足します。
7. **生データの置き場所**：推奨は **`data/raw/<提供元>/<city>_<年>.<csv|json>` に応答をそのまま保存し、あれば使う**。取り直すときは人間がファイルを消す。
8. **Jupyter の画面を依存に入れるか**：推奨は **入れない**（実行に必要な `ipykernel` と `nbmake` だけ。編集は VS Code などで行う）。
9. **分割**：推奨は **分けない**（spec の機能 #8 を 1 つの PR で）。Red は `ml/` → クライアント → ノートブックの順に区切って報告します。

## 実装時の変更

### 承認（2026-10-12 人間「推奨でお願いします」）

- 調査結果の「決めてほしいこと」A〜G を **すべて推奨どおり** で承認。ブロッカー 1・2 は解消。

### Red（2026-10-12）

- ブランチ `feature/issues_15`。依存を追加した：`ml` グループに pandas 3.0.6・pyarrow 26.0.0、`dev` に nbmake 1.5.5・ipykernel 7.4.0・nbstripout 0.9.1・pandas-stubs。`[tool.uv] default-groups = ["dev", "ml"]` で、`uv sync` が `ml` も入れるようにした。
- **この PC（Windows）では pandas を import できない**：numpy の DLL（`_umath_linalg`）が、Windows のアプリケーション制御ポリシーで読み込みを止められる（2 回試して同じ。pyarrow は import できた）。計画のリスクに「ノートブックのカーネルが止められる可能性」と書いていたものが、pandas そのもので起きた。
  - 回避はしていない。**`ml/` を使うテスト・mypy・nbmake は、Docker（Linux）の中で実行している**。確認用のイメージは `python:3.14-slim` に uv 0.13.0 を入れ、`uv sync --locked`（dev + ml）をしたもので、リポジトリを載せて実行する。イメージの定義は作業用の場所に置き、リポジトリには入れていない。
  - **手元（Windows）で `uv run pytest` を実行すると、`tests/ml/` は収集エラーになる**。CI（Linux）は影響を受けない見込み（未確認。PR で確かめる）。
- **fixture**（`tests/fixtures/data_raw/`）：調査で取得した 3 つ（RJTT・EDDB の METAR、ベルリンの気象）をそのまま置き、東京の気象を 1 回取得した（2026-10-12T20:53Z、200）。生データと同じ並び（`<提供元>/<city>_2025.<csv|json>`）で、中身は 2025-01-15〜16 の 2 日ぶん。
  - METAR の fixture は、決めた列（B）より多い列（`relh`・`drct`・`sknt`・`alti`・`mslp` を含む 18 列）で取得してある。整形は必要な列だけを使い、余分な列は無視する（テストあり）。
- **Red の確かめ方**：実装の前に「何もしない骨組み」（`app/clients/bulk.py`・`iem.py`・`open_meteo_archive.py`、`ml/metar.py`・`archive.py`・`dataset.py`・`raw_store.py` の関数の形だけ。中身は `NotImplementedError`）を置いた。設定（`app/config.py`）と `app/cities.py` は変えていない。ノートブックは先に書いた。
  - 結果（Docker の中）：**177 件が失敗、601 件が通過、収集エラーなし**（既存の 597 件はすべて通過）。`pytest --nbmake notebooks/` は **1 件失敗**（`'Settings' object has no attribute 'iem_base_url'`）。ruff・mypy は通る。
  - 失敗の内訳：`test_bulk_clients.py` 71、`test_config.py` 9、`test_archive.py` 24、`test_dataset.py` 22、`test_metar.py` 37、`test_raw_store.py` 14。
  - 骨組みでも通る新しいテスト 4 件：fixture にシーリングのある行・ない行の両方が入っていること（fixture の確認で、実装は見ない）、ノートブックが存在すること、出力が残っていないこと、手元のパスなどが入っていないこと（3 件ともノートブックのファイルを見るテストで、ファイルを先に書いたため）。何も確かめていないテストはなかった。
- **計画から変えた点**（骨組みを書く前に人間に伝えた）：
  - `app/clients/bulk.py`（新規）：2 つのクライアントに共通の、タイムアウトとリトライ。
  - クライアントは応答の本文（文字列）を返す。過去データも JSON の文字列のまま返し、`ml/archive.py` が読む（生データを応答のまま保存するため）。
  - fixture の置き場所を `tests/fixtures/data_raw/` にした（計画は `tests/fixtures/iem/` など）。
  - 設定 `IEM_REQUEST_INTERVAL_S`（既定 2 秒、1 秒未満は受け付けない）を足した。
  - クライアントのテストは 1 ファイル（`tests/app/test_bulk_clients.py`）にまとめた。
- **計画になかった変更**（Red の報告で人間に伝える）：
  - `pyproject.toml` の ruff に、ノートブックだけ E402（import がセルの先頭にない）を許す設定を足した。ノートブックは最初のセルでリポジトリの場所を `sys.path` に足してから `app`・`ml` を import するため。
  - 年の範囲（1940〜2100）をクライアントで検証する（過去データが 1940 年からあることは公式ドキュメントで確認。上限の 2100 は `/daylight` の日付の範囲に合わせた。spec にはない）。
- **計画から増減したテスト**：
  - 足したもの：気温・露点が電文の値（摂氏の整数）に戻ること、`ceiling_m` が電文の BKN・OVC の最も低い高さと一致すること（どちらも、IEM の列ではなく電文そのものを期待値にした）、余分な列を無視すること、入力の順に左右されないこと、空の応答を保存しないこと、失敗の後に取り直せること、IEM の 200 で CSV でない本文、接続先の設定、全体のタイムアウト、年の範囲。
  - 結合のテストで、fixture から分かった報告の時刻を使った：東京は正時の報告がそのまま付く、ベルリンは 10 分前（毎時 50 分）の報告が付く（fixture の最初の正時だけ 20 分後）。
- **未決（Red の報告で相談）**：`ml` グループを既定で入れる設定にしたので、いまの Dockerfile（`UV_NO_DEV=1`）では、API のイメージにも pandas・pyarrow が入る。計画は「API のイメージには入れない」。Dockerfile は計画のファイル一覧にないので、まだ変えていない。
- **外部APIの呼び出し回数**（ここまで）：IEM 2 回、Open-Meteo の過去データ 2 回（調査 1、fixture 1）。ドキュメントのページ 5 回。

### Green・Refactor（2026-10-12、人間「実装へ進んで」）

- **Dockerfile は変えていない**。Red の報告で「変えるか」を聞いたが、回答は「実装へ進んで」だけだったので、触らなかった。**いまのままだと、API のイメージにも pandas・pyarrow が入る**（計画は「入れない」）。未決のまま。
- **結果**（Docker の中）：778 件が通過（#7 の終わりは 597 件）。`pytest --nbmake notebooks/` も通過。ruff・mypy も通る。
- **最初の実装では 2 件が失敗した**（修正回数：2）：
  1. `test_clients_enforce_total_timeout`（テストを直した）：途中で打ち切った要求は respx の `call_count` に数えられないことを知らずに、`call_count == 1` と書いていた。要求が始まった回数を自分で数える形にした。「全体のタイムアウトで `UpstreamError` になる」という確かめる内容は変えていない。
  2. `test_dataset_roundtrips_through_parquet`（実装を直した）：時刻の列を秒の細かさにしていたが、parquet に保存して読み直すとミリ秒になって戻る。時刻の列をミリ秒にそろえた（`ml/archive.py` の `TIME_UNIT`）。
  - ほかに mypy が 2 回（`as_unit` の戻り値・引数の型）。
- **実装をわざと壊して、テストが失敗することを確かめた**（30 通り。1 つずつ壊して全テストを実行し、元に戻して 778 件が通ることを確認）：
  - 検出できたもの 29。
  - 検出できなかったもの 1：結合で「UTC でないタイムゾーンの時刻を受け付ける」。この確認を外しても、後の結合（pandas）が同じ種類のエラーで拒否するので、結果が変わらない。
  - **この確認の途中で、fixture を 1 つ壊した**：「保存済みでも取得する」ように壊したとき、`test_raw_store_reads_existing_file_without_fetching` が fixture の場所（`tests/fixtures/data_raw/iem/tokyo_2025.csv`）をそのまま読んでいたため、壊れた実装が fixture を「should not be used」という文字列で上書きした。その後の 12 通りは、fixture が壊れた状態で実行され、別の理由で失敗していた（結果は無効）。
    - 気づいたきっかけ：元に戻した後の全テストが 25 件失敗した。
    - 対応：調査のときの応答（作業用の場所に残っていた、同じ内容のファイル）から復元し、内容が一致することを確かめた。ほかの 3 つの fixture は無事だった。テストを、fixture の写しを読む形に直した（実装が壊れていても fixture を書き換えない）。無効だった 12 通りをやり直した（上の数はやり直した後のもの）。
    - 外部APIの取り直しはしていない。
- **全期間の取得**（2026-10-12T21:33:53Z〜21:35:58Z、Docker の中で `DATA_FETCH_MODE=full`）：
  - 外部APIの呼び出しは **32 回**（IEM 16、Open-Meteo の過去データ 16）。すべて成功し、リトライ・429 はなかった（ノートブックが 1 回で通った）。全体で約 2 分。
  - 生データ：IEM は 1 年あたり 1.9〜2.8 MB、Open-Meteo は 1 年あたり約 0.47 MB。`data/raw/` は合わせて約 44 MB。
  - 成果物：`data/processed/observations.parquet`、約 7.0 MB、**140,256 行・28 列**（都市ごとに 70,128 行 ＝ 8 年ぶんの正時）。期間は 2018-01-01T00:00Z〜2025-12-31T23:00Z。
  - **ネットワークを切って（`--network none`）もう一度実行しても通り、同じ内容のファイルができた**（ハッシュが一致。約 16 秒）。再実行で外部APIを呼ばないことの確認。
  - `data/` は git の対象外であることを確かめた。

  | | 東京（RJTT） | ベルリン（EDDB） |
  |---|---|---|
  | 行数 | 70,128 | 70,128 |
  | METAR が付かなかった正時 | 6 | 7 |
  | 付いた METAR の時刻 | 正時ちょうど 70,109、30 分前 10、30 分後 3 | 10 分前 70,104、20 分後 17 |
  | 気象の列の欠損 | なし | なし |
  | `ceiling_m` がある行 | 29,411（41.9%） | 21,629（30.8%） |
  | `ceiling_m` の中央値・最小・最大 | 1,371.6 m・30.5 m・7,010.4 m | 640.1 m・30.5 m・9,144.0 m |
  | BKN・OVC の層があるのに `ceiling_m` が欠損の行 | **11,397** | 16 |
  | 高さのない BKN・OVC を飛ばして、別の層から `ceiling_m` が決まった行 | **1,653** | 15 |

- **#9（EDA）への申し送り**（今回は決めていない。事実だけ）：
  - **東京は、高さのない BKN・OVC の層がとても多い**（電文の `BKN///`。13,050 層）。そのため、BKN・OVC があるのに `ceiling_m` が欠損の正時が 11,397 ある（東京の 16%）。「雲がない」のではなく「高さが分からない」欠損で、シーリングなしとは意味が違う。
  - 高さのない層を飛ばして、別の（高さのある）BKN・OVC から `ceiling_m` が決まった正時が、東京で 1,653 ある。飛ばした層のほうが低い可能性があり、その場合は実際より高い値になっている。例：`FEW050 BKN///`。
  - 雲の量の列には、BKN・OVC・FEW・SCT のほかに `NSC`・`NCD`・`VV `（末尾に空白がある）が入っていた。`VV`（鉛直視程。霧のとき）は spec の定義ではシーリングに数えていない（東京 1、ベルリン 228）。高さのない `VV///` もある。
  - `ceiling_m` がある行は、東京 42%・ベルリン 31%。
  - ベルリンは、付いた METAR がほぼすべて正時の 10 分前（毎時 50 分）の報告。東京は正時の報告。
- **手動確認の残り**：`/docs` などの画面はない（API のエンドポイントは足していない）。CI での nbmake は、PR を作って確かめる（未確認）。
- **`.env.example` を更新できていない**（AI は書けない）。**人間の対応が必要**。追記する変数名：`IEM_BASE_URL`、`OPEN_METEO_ARCHIVE_BASE_URL`、`DATA_FETCH_TIMEOUT_S`、`IEM_REQUEST_INTERVAL_S`。ノートブックの切り替え用の `DATA_FETCH_MODE`（`sample`／`full`）は、設定（`Settings`）ではなくノートブックが直接読む。
- **spec.md に書いたこと**：外部API表（IEM と過去データのAPIを確認済みに）、一括取得のタイムアウト・間隔と環境変数、「データ取得（#8 で決めたこと）」と列の一覧、CI の nbmake、機能一覧 #8 を完了に。
- **外部APIの呼び出し回数**（#8 の合計）：IEM 18 回（調査 2、全期間 16）、Open-Meteo の過去データ 18 回（調査 1、fixture 1、全期間 16）。ドキュメントのページ 5 回。計画の見積もり（本番 32、fixture 4、確認で数回）に対して、fixture は 1 回で済んだ。テスト・CI からは 0 回。
- **残っているリスク**：
  - この PC では `ml/` のテストを直接実行できない（Docker が要る）。確認用のイメージの定義はリポジトリにない。
  - API のイメージに pandas が入る（上の未決）。
  - 1 年ぶんの取得は、今回は 60 秒のタイムアウトに十分収まった（32 回で約 2 分）。混雑時（503）は試していない。

### レビュー後の変更（2026-10-12、人間「推奨でお願いします」）

レビューで「🔴 の 2 点と 🟡 の 5 点を修正案のとおり直す」を推奨として示し、そのとおり対応した。🟢 は対応していない。

- **`Dockerfile.dev`（新規）と CLAUDE.md の「コマンド」**：pandas を読み込めない PC で、テスト・mypy・nbmake を Docker の中で実行するためのイメージの定義をリポジトリに入れた（作業用の場所に置いていたものと同じ内容に、非 root のユーザーを足した）。CLAUDE.md に実行方法を 3 行足した。このイメージで全チェックが通ることを確かめた。
- **`Dockerfile`**：`uv sync` に `--no-group ml` を足した。ビルドして、API のイメージに pandas・pyarrow・numpy が入っていないこと、`app.main` を import できることを確かめた（イメージの中の `.venv` は 341 MB → 31 MB）。
- **`nbstripout` を依存から外した**（どこからも使っていなかった。出力が残っていないことは `tests/test_notebooks.py` が確かめている）。
- **テストを足した**：`test_clients_do_not_retry_non_transport_errors`（`DecodingError`・`TooManyRedirects` × 2 つのクライアント。1 回だけ呼んで `UpstreamError`）。実装が先にあるテストなので、その分岐をリトライするように壊して 4 件が失敗することを確かめ、元に戻した。`app/clients/bulk.py` のカバレッジは 94% → 100%。
- **spec に書いた**：取得できる年は 1940〜2100 年（AI が決めていた値。レビューで示し、そのまま認める回答をもらった）。高さのない BKN・OVC の層の件は「未決（#9 で決める）」として件数と一緒に書いた。API のイメージに `ml` を入れないこと、`Dockerfile.dev` のこと。
- **`.gitattributes`（新規）**：`tests/fixtures/**` の改行を変換しない。
- 結果：782 件が通過、カバレッジ 99.23%、ruff・mypy・nbmake・pip-audit 問題なし（`Dockerfile.dev` のイメージの中）。
- **対応していないもの**（🟢）：雲の量の値の前後の空白（`VV `）、`# type: ignore` 1 つ、spec の IEM の利用条件の注記（「All rights reserved」の表示）、METAR が正時より後になる行の申し送り、`tests/test_notebooks.py` の形だけに近い確認、同じ時刻に内容の違う報告が 2 つある場合の扱い。
