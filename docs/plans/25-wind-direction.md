# 計画：#25 の追加 今日の天気の風向（Issue #58）

状態：承認済み（2026-10-19。質問 1〜7 はすべて「おすすめ」で決定）

## 決定事項（2026-10-19、人間の承認）

1. キーは `wind_direction_deg`。値は Open-Meteo の度のまま返し、8 方位の名前は画面（JS）で決める。
2. テストの直し方は A：fixture は `/weather` の組（4 つ）だけ取り直す。「キャッシュを共用する」「時刻がそろう」テストは新しい組（`load_forecast`・`FIXED_NOW`）に替え、「項目のない保存値」のテストは `seed_weather_cache` で保存先に直接入れる。確かめる中身は変えない。
3. fixture は AI が `curl` で `api.open-meteo.com` を 4 回呼んで取得し、取得したまま `forecast_<city>_direction.json`・`forecast_<city>_direction_iso8601.json` に保存する。`_wind` の組は「風向のない保存値」のテスト（D7・D8）に残す。
4. 風向は数値（小数も受ける）。範囲の検証はしない（テスト一覧の「質問 4 の範囲の検証」の行は行わない）。
5. 画面：8 方位（比較ページと同じ区切り）。「現在」の図は風配図の枠の中に風の流れていく向きの矢印と「北東の風 3.4 m/s」。表は「風」の列に「↙ 北東 3.4 m/s」。表の下に「風向は風の吹いてくる方向（Open-Meteo の予報）」と注を書く。
6. 風の弱いときも特別な扱いをせず、0.0 m/s でも方位を出す。
7. 画面を見ての追加の要望は、そのつど「別の Issue にするか、この Issue に足すか」を聞く。

## 目的と受け入れ条件

Issue #58 から（spec.md の機能 25 の行に「今日の天気の風向きは #58」とある。spec の本文にはまだない）：

- 今日の天気の画面で、風がどこから吹いているかを分かるようにする。
- 「現在」の欄に、比較ページの風配図と同じ見た目の図を出す（矢印で風向、風速も書く）。
- 「24 時間の予報」の表に、風向を足す（例：「北東 3.5 m/s」）。
- `/weather` の `current`・`hourly` に風向を足す（Open-Meteo の `wind_direction_10m`。spec 7 の「予報の風向」で確認済み。吹いてくる方向であることは公式の記述ではなく、実データとの比べ合わせによる）。
- テスト用の Open-Meteo の応答を、風向を頼む URL で取り直す。

受け入れ条件（案。質問 1〜6 の答えで spec.md に書く）：

1. `/weather` の `current` と `hourly` の各行に `wind_direction_deg`（Open-Meteo の値のまま、度。北 0・東 90、吹いてくる方向）がある。
2. 返す範囲（`current`、`hourly` の 24 件）で風向が欠けている・null・数値でない場合は 502 `upstream_error`（ほかの項目と同じ）。
3. 風向のない保存値（このブランチより前に保存されたもの）は、TTL の内でも使わずに外部APIを呼び直す。外部APIも失敗したら 502（`/weather` のいまの決まりのまま）。
4. `/cloud-base`・`/cloud-base/forecast`・`/cloud-base/history`・`/cloud-history`・`/sunshine` の応答は変わらない。
5. 画面の「現在」に風の図（比較ページの風配図と同じ枠・同じ 8 方位）と「北東の風 3.4 m/s」、24 時間の予報の表の風の列に「北東 3.4 m/s」が出る。
6. 方位の区切りは比較ページと同じ 8 方位（北は 337.5° 以上・22.5° 未満。`ml/climate.py` の `WIND_SECTORS`）。

## 今回やらないこと

- `/cloud-base` のモデルの特徴量に風向を足すこと（モデルは変えない）。
- 突風（`wind_gusts_10m`）や、10 m 以外の高さの風（spec の表で未確認）。
- 7 日間（`daily`）の風向（`wind_direction_10m_dominant` は spec の表で未確認）。
- 比較ページ（`/compare`）の変更。
- JS の自動テスト（spec「JS の動作は自動テストせず、手元のブラウザで確かめる」のまま）。

## 変更・追加するファイル

| ファイル | 内容 |
|---|---|
| `app/clients/open_meteo.py` | `CURRENT_VARIABLES`・`HOURLY_VARIABLES` に `wind_direction_10m` を足す |
| `app/services/weather.py` | `_RawCurrent` に `wind_direction_10m` を足し、`current.wind_direction_deg` に入れる |
| `app/services/forecast.py` | `_RawHourly` に `wind_direction_10m`、`build_hourly` で `wind_direction_deg` を入れる |
| `app/schemas.py` | `CurrentWeather`・`HourlyForecast` に `wind_direction_deg` |
| `app/static/app.js` | 「現在」の「風速」タイルを風の図に替える。表の「風速」の列を「風」にし「北東 3.4 m/s」と矢印。8 方位の表（`compare.js` と同じ。ファイルを分けずに写す）と、度を方位にする関数 |
| `app/static/style.css` | 風の図・矢印の見た目（比較ページの `rose-ring` などを使い回す） |
| `app/static/index.html` | 表の下の注（風向は吹いてくる方向・Open-Meteo の予報）を足す |
| `tests/fixtures/open_meteo/forecast_<city>_direction.json`・`_direction_iso8601.json`（4 つ） | いまのアプリの URL（`wind_direction_10m` を足したもの）で取り直した応答（取得したまま） |
| `tests/fixtures/README.md` | 取り直した 4 つの取得日時・URL・中身の要点。`_wind` の組を「風向のない保存値」のテストに残すこと |
| `tests/conftest.py` | `load_forecast`・`load_forecast_iso8601` を `_direction` の組に替え、`FIXED_NOW` を取得時刻の直後に。`_wind` の組を読む `load_wind_forecast` と `WIND_NOW` を足す |
| `tests/app/test_weather_*.py` | 時刻を直接書いた期待値（`2026-10-19…`）を、取り直した fixture の時刻に読み替える（約 27 か所。数え方は「リスク」） |
| `tests/app/test_cloud_base*_router.py`・`test_cloud_history_router.py`・`test_sunshine_router.py`・`test_daylight_router.py` | `/weather` を通すテスト（約 18 関数）を直す。質問 2 |
| `tests/app/test_weather_direction.py`（新規） | 風向のテスト（下の一覧） |
| `docs/spec.md` | `/weather` の例と決まり、画面の節、機能 25 の行 |

## テスト一覧（先に書く順）

| # | テスト名 | 種類 | 確かめること |
|---|---|---|---|
| D1 | `test_client_requests_wind_direction` | 正常 | 送る URL の `current`・`hourly` に `wind_direction_10m` がある（respx で送った引数を見る） |
| D2 | `test_current_has_wind_direction`（2 都市） | 正常 | `current.wind_direction_deg` が fixture の `current.wind_direction_10m` と同じ |
| D3 | `test_hourly_has_wind_direction`（2 都市） | 正常 | `hourly` の 24 件の `wind_direction_deg` が、fixture の同じ時刻の行の値と同じ |
| D4 | `test_current_wind_direction_missing_or_null_is_502`（欠け・null・文字列・真偽値） | 異常 | 502 `upstream_error` |
| D5 | `test_hourly_wind_direction_missing_or_null_is_502`（欠け・範囲の中の null・列の長さ違い） | 異常 | 502 `upstream_error` |
| D6 | `test_hourly_wind_direction_null_outside_window_is_ok` | 境界 | 返す 24 件の外の null は見ない（200） |
| D7 | `test_weather_refetches_when_cached_entry_lacks_direction` | 異常 | `_wind` の組を保存先に入れ、TTL の内でも外部APIを呼び直し、風向のある応答を返す |
| D8 | `test_weather_old_entry_without_direction_and_upstream_failure_is_502` | 異常 | 上の保存値があって外部APIが 500 なら 502（stale で返さない） |
| D9 | `test_other_endpoints_unchanged_with_direction`（5 つのエンドポイント） | 正常（Red にならない） | 風向のある応答と、風向を消した応答で、`/cloud-base` など 5 つの応答が同じ。いまの動作を守るテスト |
| D10 | `test_weather_keys` | 正常 | `current`・`hourly` の行のキーの集合に `wind_direction_deg` が入る（いまのキーのテストを書き換える。キーが増えるので Red になる） |
| ― | 質問 4 の範囲の検証を入れる場合 | 異常・境界 | −1・361 は 502、0・360 は 200 |

- 画面（風の図・表・方位の区切り・静穏のとき）は、手元のブラウザで確かめる（spec の決まり）。確かめる点：東京・ベルリンで「現在」の図の矢印と文字の方位がそろう／表の 24 行に方位が出る／`prefers-reduced-motion`・暗い配色で見える／幅の狭い画面で崩れない。

## 追加する依存パッケージ

なし

## セキュリティ上の注意

- 入力検証：利用者の入力は増えない（`city` のまま）。Open-Meteo の値は pydantic の strict で型を確かめる（範囲は質問 4）。
- シークレット：なし。
- 外部通信（ホスト・タイムアウト）：`api.open-meteo.com` への 1 回の呼び出しに項目を 1 つ足すだけ。タイムアウト・リトライは変えない。画面は外部から読み込まない。値は `textContent`・SVG の属性で入れる（`innerHTML` を使わない）。
- fixture の取得：`curl` で `api.open-meteo.com` を 4 回呼ぶ（質問 3）。

## リスク・未決事項

- **テストへの影響（数えたもの）**：
  - `/weather` のテスト（`test_weather_*.py` の 5 ファイル）は `load_forecast` を使うので、fixture を替えれば通る。ただし時刻を直接書いた期待値が約 27 か所（`test_weather_cache` 11・`stale` 7・`router` 5・`forecast` 3・`service` 1）あり、読み替えが要る。
  - `/weather` をほかの fixture（`_cloud_base`・`_past`・`_sun`）で通しているテストが 6 ファイル・約 18 関数（パラメータを数えるとさらに多い）。風向を必須にすると、これらは 502 で失敗する。Issue の「151 個失敗」の大半は上の 5 ファイル、残りがここ。
- ほかの fixture まで取り直す案（質問 2 の B）は、基準の時刻 3 つ（`CLOUD_BASE_NOW`・`PAST_NOW`・`SUN_NOW`）と、時刻を直接書いた期待値 約 40 か所が変わり、`_cloud_base` の東京の先頭の行が `LEGACY_NOW` の正時と同じであることに頼るテスト（README の注）が壊れる。
- 風向が「吹いてくる方向」であることは、公式の記述ではなく実データとの比べ合わせ（spec 7 の表）。画面の注にそう書くかは質問 5。
- 風の弱いとき（東京は 1〜4 kt で METAR とのずれが大きかった）の方位は当てにならない。静穏の扱いは質問 6。

## ブロッカー（人間の対応が必要なこと）

- なし（`wind_direction_10m` は spec 7 の表で確認済み）。fixture の取得に外部通信の承認が要る（質問 3）。

## 質問

1. **応答のキーの名前**：`wind_direction_deg`（おすすめ。`wind_speed_ms` と同じく単位を名前に入れる）／`wind_direction`。値は度のまま返し、8 方位の名前は画面（JS）で決める（おすすめ。API に方位の名前を足さない）でよいですか。
2. **ほかの fixture で `/weather` を通しているテスト（約 18 関数）の直し方**：
   - A（おすすめ）：fixture は `/weather` の組（4 つ）だけ取り直す。新しい組はいまのアプリの URL で取るので、`_cloud_base`・`_past`・`_sun` の項目もすべて入っている。「キャッシュを共用する」「時刻がそろう」テストは新しい組（`load_forecast`・`FIXED_NOW`）に替え、「項目のない保存値」のテストは `/weather` を通さずに保存先に直接入れる（`seed_weather_cache`。#25 の追加の `test_cloud_base_refetches_when_cached_entry_lacks_new_items` と同じやり方）。確かめる中身は変えない。
   - B：Issue の案どおり、`_cloud_base`・`_past`・`_sun` の組も取り直す（8 ファイル増、基準の時刻 3 つ・期待値 約 40 か所の読み替え、`LEGACY_NOW` に頼るテストの作り直し）。
3. **fixture の取得**：AI が `curl` で `api.open-meteo.com` を 4 回呼び（東京・ベルリン × UNIX 秒・ISO 8601）、取得したまま保存してよいですか（おすすめ：はい。#25 の追加と同じ）。ファイル名は `forecast_<city>_direction.json`（おすすめ）、いまの `_wind` の組は「風向のない保存値」のテスト（D7・D8）に残します。
4. **風向の値の検証**：
   - 型：数値（小数も受ける。おすすめ。実データは整数だったが、公式に整数とは書かれていない）／整数だけ。
   - 範囲：0〜360 の外なら 502 にする／しない（おすすめ：しない。ほかの項目（気温・雲量）も範囲を見ていないので、spec にない検証を足さない）。
5. **画面の見た目**：
   - 方位：8 方位（おすすめ。比較ページと同じ区切り）／16 方位。
   - 「現在」の図：比較ページの風配図の枠（円 2 つ・東西南北の文字）の中に、**風の流れていく向きに矢印**を描き（北東の風なら、北東の縁から南西へ向かう矢印）、下に「北東の風 3.4 m/s」（おすすめ。天気の画面でよく見る向き）／吹いてくる方向を指す矢印。
   - 表：いまの「風速」の列を「風」にし、「↙ 北東 3.4 m/s」のように小さな矢印と方位と風速を 1 つのセルに（おすすめ。Issue の例の形）／風向の列を別に足す。
   - 注：表の下に「風向は風の吹いてくる方向（Open-Meteo の予報）」と書く（おすすめ）。
6. **風の弱いとき**：spec に決まりがありません。A（おすすめ）：特別な扱いをせず、0.0 m/s でも方位を出す（このサイト独自の閾値を作らない）／B：表示が「0.0 m/s」のときは「静穏」と出して矢印を描かない（このサイト独自の目安として spec に書く）。
7. 画面を見ながら追加の要望が出たら、そのつど「別の Issue にするか、この Issue に足すか」を伺います。

## 実装時の変更

- D4・D5・D6 の欠け・null は、新しいファイルに書かず、既存の一覧（`tests/app/test_weather_service.py` の `REQUIRED_FIELDS`、`tests/app/test_weather_forecast.py` の `HOURLY_FIELDS`）に `wind_direction_10m` を足して確かめた。既存のテストがこの一覧で欠け・null（範囲の中・外）を確かめる作りで、同じことを二重に書かないため。型違い（文字列・真偽値）、列の短さ、小数は `tests/app/test_weather_direction.py` に書いた。
- `tests/app/test_cloud_base_forecast_service.py`・`tests/app/test_sunshine_service.py` の「時刻が `/weather` の hourly と同じ」テスト（14 件）も、比べる相手の `build_hourly` に `_past`・`_sun` の fixture を通していたので、A 案と同じやり方（`load_forecast` と `FIXED_NOW` のまわりの時刻）に直した。計画の一覧になかったので、直す前に人間に確認した（2026-10-19、承認）。計画の数え方はルーターの `/weather` の呼び出しだけを見ていて、サービスの関数を直接呼ぶテストを見落としていた。
- 「項目のない保存値」のテストを `seed_weather_cache` に替えたので、外部APIを呼ぶ回数の期待値が 2 から 1 になった（前は 1 回目が保存値を作るための `/weather` の呼び出しだった）。確かめること（TTL の内でも 1 回だけ呼び直し、その応答を保存する）は同じ。
- `tests/app/test_cloud_base_router.py` の `_started_client` に、時計の時刻を渡す引数（既定は `CLOUD_BASE_NOW`）を足した。起動のテストで `/weather` を新しい組で通すため。
- fixture の取り直しで `current.weather_code` が変わった（東京 2→51、ベルリン 0→2）。`test_service_classifies_fixture_weather_code` の期待値は、fixture の値と spec の「天気の分類」の表から読み替えた（drizzle・partly_cloudy）。
- 計画のテスト一覧の D10（`test_weather_keys`）は、新しいテストではなく、既存のキーの集合（`tests/app/test_weather_router.py` の `CURRENT_KEYS`・`HOURLY_KEYS`）に `wind_direction_deg` を足した。一覧にないテストとして、fixture の単位の契約（`test_fixture_has_wind_direction_in_degrees`）と、ルーターを通した値の確認（`test_weather_returns_wind_direction`）を足した。
- `/review` の指摘で、NaN・無限大の風向を 502 にした（`app/services/forecast.py` の `FiniteFloat`。`Field(allow_inf_nan=False)`）。受け付けると、応答で `null` になって 200 で返っていた（レビューでは 500 と見込んだが、テストを書いて実行すると 200 だった。pydantic の書き出しの既定）。人間の判断で風向だけに付け、ほかの項目は別の Issue にする（2026-10-19）。
- 風向の注は、HTML に直接書かず、日差しの注と同じく JS（`renderHourly`）で出す形にした（`/weather` が失敗して表が空のとき・読み込み中に出さないため。`/review` の指摘）。
- 8 方位に分ける JS の関数（`windSector`）は、spec の決まりで自動テストをしていない。境目（0・22.4・22.5・67.5・180・202・337.4・337.5・359・360）は node で 1 回計算して確かめた。
