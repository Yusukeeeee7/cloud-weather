# 計画：#4 天気予報（時間・日）（Issue #7）

状態：承認済み

## 目的と受け入れ条件

spec.md「14. 機能一覧」より：

> | 4 | 天気予報（時間・日） | `hourly` 24件・`daily` 7日分が仕様どおり。日付は現地の日付で区切られる |

spec.md「5. API仕様」`GET /weather?city=tokyo` より（今回追加するのは `hourly` と `daily`）：

```json
"hourly": [
  {
    "time": "2026-10-12T04:00:00Z",
    "weather_code": 3,
    "weather": "cloudy",
    "temperature_c": 21.8,
    "precipitation_probability": 20,
    "precipitation_mm": 0.0,
    "cloud_cover": {"total": 70, "low": 50, "mid": 20, "high": 0}
  }
],
"daily": [
  {
    "date": "2026-10-12",
    "weather_code": 61,
    "weather": "rain",
    "temperature_max_c": 24.1,
    "temperature_min_c": 17.5,
    "precipitation_probability_max": 60,
    "precipitation_sum_mm": 4.2,
    "sunrise": "2026-10-11T20:41:00Z",
    "sunset": "2026-10-12T08:12:00Z"
  }
]
```

関連する要件：

- spec 5：`hourly` は現在時刻以降の 24 件、`daily` は今日から 7 日分
- spec 5 共通：時刻は ISO 8601（UTC、末尾 `Z`）。日付は現地の日付（`YYYY-MM-DD`）
- spec 3：日単位のデータは、その都市の **現地の日付** で区切る
- spec 5：#4 で `hourly`・`daily` を追加する。`cached`・`stale` は返さない（#5・#6 の計画で決める）
- spec 6：現在・時間ごと・日ごとを **1 回の外部呼び出し** でまとめて取得する
- spec 5：天気コードの分類は #3 の対応表をそのまま使う（未知コードは `unknown`）
- spec 12：外部APIは `respx` でモックし、`tests/fixtures/` の保存済み実レスポンスを使う

完了の確認方法：

1. `uv run pytest --cov=app --cov=ml` が通る（カバレッジ 80% 以上）
2. `uv run ruff check . && uv run ruff format --check .`、`uv run mypy app ml` が通る
3. 手動で 1 回、Docker で起動して `/weather?city=tokyo` と `/weather?city=berlin` を呼び、`hourly` が 24 件・`daily` が 7 件で、`daily[0].date` が現地の今日であることを見る（外部API 2 回。#3 と同じく `uv run uvicorn` は Windows のポリシーで起動できないため Docker を使う）

## 今回やらないこと

- キャッシュ、`cached`・`stale`（→ #5・#6）
- リトライ、stale の返却（→ #6）
- `pressure_msl`（spec 7 の表の hourly の候補にあるが、`/weather` のレスポンスには出てこない。ML の特徴量用とみられるため #12 推論API で扱う。今回は要求しない）
- `hourly` に `dew_point_c`・`relative_humidity`・`wind_speed_ms`・`apparent_temperature_c` を足すこと（spec の `hourly` の例にない）
- `/daylight`（→ #7）。`daily` の `sunrise`・`sunset` は Open-Meteo の値をそのまま UTC に直して返すだけで、自前の計算はしない
- 件数や日数をクエリで変えられるようにすること（`hours=`、`days=` など。spec にない）
- Discord 通知・UI での利用（→ #13・#15）

## 変更・追加するファイル

| ファイル | 内容 |
|---|---|
| `app/clients/open_meteo.py` | 同じ 1 回の呼び出しに `hourly=`・`daily=` と、タイムゾーン・時刻形式のオプションを足す（パラメータ名は下の「確認が必要な項目」が確定してから）。`HOURLY_VARIABLES`・`DAILY_VARIABLES` を `CURRENT_VARIABLES` と並べて定義する |
| `app/services/weather.py` | `_RawHourly`・`_RawDaily`（列ごとの配列の検証）を追加。「現在時刻以降の 24 件」を選ぶ処理、日ごとの 7 件を組み立てる処理、時刻の UTC への変換。`current.time` の変換も新しい時刻形式に合わせて見直す |
| `app/services/forecast.py`（新規・必要なら） | `weather.py` が大きくなる場合に、`hourly`・`daily` の検証と整形を分ける。実装時に行数を見て決める |
| `app/schemas.py` | `HourlyForecast`・`DailyForecast` を追加し、`WeatherResponse` に `hourly: list[HourlyForecast]`・`daily: list[DailyForecast]` を足す |
| `app/cities.py` | 変更なしの見込み（タイムゾーン名は既にある） |
| `tests/fixtures/open_meteo/forecast_tokyo.json`、`forecast_berlin.json` | 新しいクエリ（current＋hourly＋daily）での実レスポンス。加工せず保存 |
| `tests/fixtures/open_meteo/forecast_current_*.json` | 削除する（下の「既存テストへの影響」。**ファイルの削除なので承認を求める：質問 6**） |
| `tests/fixtures/README.md` | 新しい fixture の取得日時・URL を記録 |
| `tests/conftest.py` | `load_forecast` の読み込み先を新しい fixture に変える。`FIXED_NOW` を新しい fixture の取得時刻に合わせる |
| `tests/app/test_weather_service.py`、`test_weather_router.py`、`test_open_meteo_client.py` | 下のテスト一覧の追加と、既存テストの更新 |
| `pyproject.toml`、`uv.lock` | `tzdata` を追加する場合のみ（質問 3） |
| `docs/spec.md` | 外部API表の 3 行（時間・日ごと・その他のオプション）の状態と確定したパラメータ名、今回決まった仕様（質問の回答）、機能一覧 #4 の状態 |

設計の要点：

- **外部呼び出しは 1 回のまま**。`hourly`・`daily` を足しても URL は 1 つ（spec 6）。
- **`hourly` の選び方**：Open-Meteo は数日分の時間ごとの値を列ごとの配列で返す見込み（fixture で確認）。その中から、時計（`clock()`、UTC）を基準に 24 件を選ぶ。基準の決め方は質問 1。
- **`daily` の日付**：Open-Meteo にタイムゾーンを渡し、Open-Meteo 側で現地の日付で区切った 7 日分を受け取る。自分で時間ごとの値を日ごとに集計し直すことはしない。
- **時刻の変換**：`hourly[].time`・`daily[].sunrise`・`daily[].sunset`・`current.time` は UTC の `Z` 付きで返す。タイムゾーンを渡すと応答の時刻の表し方が変わるため、受け取り方を質問 2 で決める。
- **検証は #3 と同じ厳しさ**：`strict=True` の pydantic モデルで、型違い・配列の長さの不一致・null を落とす。null の扱いは質問 4。
- **天気コード**：`classify_weather_code` をそのまま使う。未知コードのたびに警告ログが出るので、1 回の応答で最大 1 + 24 + 7 件のログになりうる（今回は抑制しない。リスクに記載）。

### 既存テストへの影響（テストを弱めないための整理）

`timezone` などを足すとクエリと応答の形が変わるため、#3 のテストの一部は **仕様の変更に合わせて更新** が必要になる。弱める変更ではないことを、ここで先に明示する。

| 既存テスト | 変更 | 理由 |
|---|---|---|
| `test_client_requests_expected_host_and_params` | 期待するクエリのキーに `hourly`・`daily`・オプションを足す。`current` の項目の一致の確認は残す | クエリが増えるため。確認する項目は増える |
| `test_weather_returns_200_and_spec_shape` | `TOP_LEVEL_KEYS` に `hourly`・`daily` を足す | spec のとおり #4 でキーが増える |
| `test_fixture_matches_requested_units` | `utc_offset_seconds == 0` の確認を、新しい時刻の受け取り方の契約に置き換える | `timezone` を渡すとオフセットが 0 でなくなる。代わりに「タイムゾーン名が要求どおり」などを確かめる |
| `test_service_time_is_utc`、`test_service_loosely_typed_value_...` の `time` の行 | 時刻形式が変わる場合、期待値の作り方と「受け付けない型」を新しい形式に合わせる | 質問 2 の結果による |
| `test_service_classifies_fixture_weather_code` | 期待する分類を、新しい fixture のコードから **承認済みの対応表（spec 5）** を引いた値に書き直す | fixture を取り直すと天気コードが変わる。実装の出力に合わせて書き換えるのではなく、fixture のコードと spec の表から決める |
| それ以外（欠損・null・型違い・未知コード・エラー系・ルーター） | 変更なし。新しい fixture でそのまま通ること | — |

### 確認が必要な項目（記憶で確定させない。ここに書いた名前は候補）

| 項目 | 候補 | 確かめ方 |
|---|---|---|
| 時間ごとの指定 | `hourly=` に項目名を並べる。項目：`temperature_2m`, `precipitation_probability`, `precipitation`, `weather_code`, `cloud_cover`, `cloud_cover_low`, `cloud_cover_mid`, `cloud_cover_high` | 人間が公式ドキュメントで確認（ブロッカー 1） |
| 日ごとの指定 | `daily=` に `weather_code`, `temperature_2m_max`, `temperature_2m_min`, `precipitation_sum`, `precipitation_probability_max`, `sunrise`, `sunset` | 同上 |
| タイムゾーン指定 | `timezone=Asia/Tokyo` / `timezone=Europe/Berlin`（#3 の計画で「IANA の名前か `auto` を指定できる」と照合済みだが、spec の表は未確認のまま）。`daily` を使うときに必須かどうかも | 同上 |
| 時刻形式 | `timeformat=unixtime`（#3 の計画で照合済み、spec の表は未確認）。このとき `daily` の `time`・`sunrise`・`sunset` がどう表されるか | 同上＋fixture の実物 |
| 予報日数 | `forecast_days=7`（既定が 7 日かどうかも） | 同上 |
| 応答の形 | `hourly`・`daily` が「列ごとの配列」（`time: [...]`, `temperature_2m: [...]`）であること、`hourly_units`・`daily_units` の有無 | fixture の実物 |
| 値の型と null | `precipitation_probability`・`precipitation_probability_max` が整数か、先の日付で null になるか | fixture の実物（質問 4） |
| `hourly` の先頭 | 現地の今日 0 時から始まるか（→ 当日の遅い時刻でも 24 件取れるか） | fixture の実物 |

ライブラリ側で実行して確かめたこと（2026-10-12、プロジェクトの `.venv`）：

- **`zoneinfo.ZoneInfo("Europe/Berlin")` は Windows の手元環境で `ZoneInfoNotFoundError` になる**（Windows には IANA のタイムゾーンのデータがなく、`tzdata` パッケージも `uv.lock` にない）。標準ライブラリだけで現地時刻を扱うことは、今の依存のままではできない。

## テスト一覧（先に書く順）

| # | テスト名 | 種類（正常/異常/境界） | 確かめること |
|---|---|---|---|
| 1 | `test_fixture_contract_hourly_daily` | 正常 | 新しい fixture が前提どおり：タイムゾーン名が要求した値、単位（°C・mm・%）、`hourly`・`daily` の各列の長さが `time` と同じ |
| 2 | `test_client_requests_hourly_and_daily_params` | 正常 | クエリに `hourly`・`daily` の項目とオプションが入る。呼び出しは 1 回のまま |
| 3 | `test_client_sends_city_timezone`（tokyo / berlin） | 正常 | 都市ごとに spec 3 のタイムゾーン名が送られる（ユーザー入力ではなく都市の定義から） |
| 4 | `test_service_hourly_has_24_items` | 正常 | `hourly` がちょうど 24 件 |
| 5 | `test_service_hourly_starts_at_or_after_now` | 境界 | 先頭の `time` が時計の時刻との関係で決めたとおり（質問 1）。時計を正時ちょうど・正時の 1 秒前・1 秒後に差し替えて確かめる |
| 6 | `test_service_hourly_is_consecutive_and_utc` | 正常 | 24 件が 1 時間おきに昇順で並び、すべて UTC |
| 7 | `test_service_hourly_maps_fixture_values` | 正常 | 選ばれた各行の値が、fixture の同じ時刻の列の値と一致する（値は fixture から読む） |
| 8 | `test_service_hourly_crosses_local_midnight` | 境界 | 時計を現地の深夜前に差し替えても、翌日にまたがって 24 件返る |
| 9 | `test_service_hourly_too_few_rows_raises_upstream_error` | 異常 | fixture の配列を切り詰めて 24 件に満たないとき `UpstreamError`（23 件だけ返さない） |
| 10 | `test_service_daily_has_7_items` | 正常 | `daily` がちょうど 7 件、日付が 1 日ずつ昇順 |
| 11 | `test_service_daily_dates_match_fixture` | 正常 | `daily[].date` が fixture の日付と一致する（Open-Meteo が現地の日付で区切った値） |
| 12 | `test_service_daily_first_date_is_local_today`（tokyo / berlin） | 境界 | **UTC の日付と現地の日付がずれる時刻**（東京：UTC 15:00〜24:00）で、`daily[0].date` が UTC の日付ではなく現地の日付になる。期待値の出し方は質問 5 |
| 13 | `test_service_daily_maps_fixture_values` | 正常 | 最高・最低気温、降水確率、降水量の合計、天気コードが fixture の値と一致 |
| 14 | `test_service_daily_sunrise_sunset_are_utc` | 正常 | `sunrise`・`sunset` が UTC で、fixture の値と同じ瞬間を指す。`sunrise < sunset` |
| 15 | `test_service_daily_sunrise_can_fall_on_previous_utc_date` | 境界 | 東京の `sunrise` の UTC の日付が `date` の前日になる（spec の例と同じ関係）。エラーにしない |
| 16 | `test_service_daily_too_few_rows_raises_upstream_error` | 異常 | 7 日に満たないとき `UpstreamError` |
| 17 | `test_service_hourly_missing_or_null_field_raises_upstream_error`（項目をパラメータ化） | 境界 | 使う 24 件の中に欠損・null があると `UpstreamError`（質問 4 の回答で確定） |
| 18 | `test_service_daily_missing_or_null_field_raises_upstream_error`（項目をパラメータ化） | 境界 | 同上（7 日分） |
| 19 | `test_service_hourly_column_length_mismatch_raises_upstream_error` | 異常 | ある列だけ短いとき `UpstreamError`（ずれた行を組み合わせて返さない） |
| 20 | `test_service_hourly_daily_wrong_type_raises_upstream_error` | 異常 | 配列でない・数値の文字列・真偽値を受け付けない |
| 21 | `test_service_hourly_daily_unknown_weather_code` | 境界 | 未知コードで `weather` が `unknown`、`weather_code` は元の値、200 のまま |
| 22 | `test_service_current_time_still_utc` | 正常 | タイムゾーンを渡すようになっても `current.time` が正しい UTC の瞬間を指す（#3 からの回帰の確認） |
| 23 | `test_weather_returns_hourly_and_daily_shape`（tokyo / berlin） | 正常 | `GET /weather` が 200。`hourly` 24 件・`daily` 7 件。各要素のキーの集合が spec と一致（余計なキーがない）。`cached`・`stale` がない |
| 24 | `test_weather_hourly_daily_times_format` | 正常 | JSON 上で `hourly[].time`・`sunrise`・`sunset` が `...Z`、`date` が `YYYY-MM-DD` |
| 25 | `test_weather_broken_hourly_returns_502` | 異常 | `hourly`・`daily` が壊れた応答で 502 `upstream_error`。`current` だけを返したりしない |

- すべて `respx` でモックし、テストから外部APIを呼ばない。
- Red の確認：グループごと（クライアント → hourly → daily → ルーター）にテストを先に書き、失敗を実行して確かめてから実装する。
- 夏時間の切り替えをまたぐ期間のテスト（ベルリン：2026-10-25）は、その期間を含む実レスポンスがないと期待値を作れない。扱いは質問 7。

## 追加する依存パッケージ

| パッケージ | 理由 | 代替案 |
|---|---|---|
| `tzdata`（本番・**質問 2・3 の回答しだい**） | 現地時刻 ↔ UTC の変換に `zoneinfo` を使う場合に必要。Windows の手元環境には IANA のデータがなく、実行して `ZoneInfoNotFoundError` を確認した。Docker の slim イメージにデータが入っているかは未確認（実装時に確かめる） | 時刻を UNIX 秒で受け取り、日付は Open-Meteo が返す値をそのまま使えば不要（質問 2 の案 A。ただし `daily` の日付が UNIX 秒でどう表されるかの確認が要る） |

採用する場合は、バージョンと Python 3.14 対応を PyPI で確かめてから承認を求め、追加後に `pip-audit` を実行する。

## セキュリティ上の注意

- 入力検証：変更なし。`city` は Enum（許可リスト）のみ。**件数・日数・タイムゾーンを利用者の入力から受け取らない**（24 件・7 日・都市のタイムゾーンはコード側で固定）。
- SSRF 対策：`timezone` のクエリ値は `app/cities.py` の定義から取り、利用者が送った文字列を URL・クエリに入れない。ホスト・パスは #3 のまま。
- シークレット：なし（API キー不要）。`.env` は読まない。
- 外部通信（ホスト・タイムアウト）：`api.open-meteo.com` のみ、接続 3 秒・全体 10 秒（#3 のまま）。応答が大きくなる（数日分 × 8 項目）が、全体のタイムアウトは変えない。
- 応答の大きさ：受け取った配列を無制限に処理しない。必要な 24 件・7 件だけを取り出し、列の長さが想定の上限を超える場合は `UpstreamError` にする（上限の値は fixture の実際の長さを見て決める）。
- エラー・ログ：#3 と同じ。応答本文の全体をログに出さない。
- 依存：`tzdata` を入れる場合のみ追加。

## 実行のたびに枠を使うものの見積もり

- 外部API（Open-Meteo）：fixture の取得 2 回、時刻形式を比べるための試し取り最大 4 回（質問 2 の 2 案 × 2 都市）、完了時の手動確認 2 回、予備を含めて **12 回以内**。テストからは 0 回。
- GitHub Actions：PR の作成で 1 回、レビュー後の修正と dev-log をまとめて 1 回の **計 2 回** を目安。

## リスク・未決事項

- **タイムゾーンを渡すと `current.time` の表し方も変わる**。#3 の「オフセットなし＝UTC」という前提（`_parse_utc`）がそのままでは誤りになる（東京で 9 時間ずれる）。テスト 22 で回帰を確かめる。
- **夏時間の切り替え**：ベルリンは 2026-10-25 に夏時間が終わる。今日（10-12）から 7 日では入らないが、10-19 以降は `daily` の 7 日間に切り替え日が入る。
  - 現地時刻の文字列で受け取る方法では、切り替えの夜に同じ時刻が 2 回現れ、UTC に直すとき曖昧になる。
  - UNIX 秒で受け取る方法では瞬間は曖昧にならないが、応答の `utc_offset_seconds` は 1 つの値なので、切り替え後の日付を自分で計算すると 1 時間ずれうる。
- **`precipitation_probability` の null**：先の時刻・日付で値がない可能性がある。質問 4 の方針（null なら 502）だと、Open-Meteo 側の事情で `/weather` 全体が 502 になる。fixture で実際に null があるかを見てから最終判断する。
- **未知コードのログが増える**：未知コードが続くと 1 応答で最大 32 件の警告になる。今回は抑制しない。
- **fixture と時計の関係**：`hourly` の 24 件は時計に依存するため、テストの `FIXED_NOW` は fixture の取得時刻に合わせる。fixture を取り直すたびに `FIXED_NOW` も変える必要がある（README に書く）。
- **Web ページの照合は人間の確認が前提**：この計画の「候補」は AI の記憶と #3 の照合結果によるもので、確定ではない。
- **Issue #7 の本文を読めていない**（`gh` がこの環境にない）。spec の機能 #4 と同じ内容という前提。

## ブロッカー（人間の対応が必要なこと）

1. **外部API表の「未確認」3 行の確認**（CLAUDE.md「未確認のものは使わない」）。公式ドキュメント <https://open-meteo.com/en/docs> で次を確かめ、結果を教えてください。合っていれば実装ブランチで spec の状態を「確認済み」に書き換えます。
   - **予報（時間）**：`hourly=` で使える項目名に `temperature_2m`, `precipitation_probability`, `precipitation`, `weather_code`, `cloud_cover`, `cloud_cover_low`, `cloud_cover_mid`, `cloud_cover_high` があること、それぞれの単位
   - **予報（日ごと）**：`daily=` の項目名 `weather_code`, `temperature_2m_max`, `temperature_2m_min`, `precipitation_sum`, `precipitation_probability_max`, `sunrise`, `sunset` と単位。`daily` を使うときに `timezone` の指定が必須かどうか
   - **オプション**：`timezone`（IANA の名前を渡せること、渡したとき応答の時刻がどう変わるか）、`timeformat=unixtime`（`daily` の `time`・`sunrise`・`sunset` がどう表されるか。日付に直すときの注意書きがあるか）、`forecast_days`（既定値と指定できる範囲）
   - 利用条件は #3 で確認済みの内容（非商用・回数の上限・CC BY 4.0）と同じでよいか
2. **fixture（実レスポンス）の取得**：ブロッカー 1 でクエリが確定した後、AI が `curl` で取得してよいか（質問 2・6 と合わせて回答をお願いします）。
3. **Issue #7 の本文**：spec の機能 #4 にない要件が書かれていれば教えてください。

## 質問

### 回答（2026-10-12 人間）

- 質問 1〜8：**すべて推奨どおり**。計画を承認。
  - 1：`hourly` は現在より後の最初の正時から 24 件（現在が正時ちょうどならその時刻を含む）。
  - 2：案 A（`timezone=<都市のタイムゾーン>` ＋ `timeformat=unixtime`）で進める。`daily` の日付を安全に取り出せないと分かったら作業を止めて相談する。両案の試し取り（最大 4 回）は可。
  - 3：`tzdata` は、必要と分かった時点で改めて承認を求める（今は追加しない）。
  - 4：返す範囲（24 件・7 日）に null・欠損があれば 502 `upstream_error`。返さない範囲の null は無視。fixture に null があれば実装前に報告する。
  - 5：UTC の日付と現地の日付がずれる時刻に取得した fixture を使い、Open-Meteo が返した日付を期待値にする。
  - 6：#3 の fixture 2 ファイルは新しい fixture に置き換えて削除する。
  - 7：夏時間の切り替え日のテストは今回の対象外とし、リスクとして記録して #7 で扱う。
  - 8：`pressure_msl` は今回要求しない。
- ブロッカー 2（fixture の取得）：質問 2・6 の回答により、AI が `curl` で取得してよい。
- ブロッカー 1（外部API表の 3 行の確認）：人間の指示により AI が確認した（「実装時の変更」を参照）。ブロッカー 3（Issue #7 の本文）：追加の要件の連絡なし。spec の機能 #4 と同じ内容として進める。

### 質問の内容

1. **「現在時刻以降の 24 件」の先頭**：たとえば現在が 13:41 のとき、先頭は 14:00（現在より後の最初の正時）と 13:00（現在を含む時間帯）のどちらですか。推奨は **14:00 から 24 件**（「以降」の文字どおり。spec の例も `current.time` 03:00 の次の 04:00 から始まっている）。現在が正時ちょうど（14:00:00）のときは 14:00 を含めます。
2. **時刻の受け取り方**（ブロッカー 1 の確認結果と fixture の実物を見て最終決定）：
   - 案 A（推奨）：`timezone=<都市のタイムゾーン>` ＋ `timeformat=unixtime`。時間ごと・日の出入り・現在の時刻が UNIX 秒になり、UTC への変換が曖昧にならない。`daily` の日付の取り出し方は公式の説明と fixture で確かめる。
   - 案 B：`timezone=<都市のタイムゾーン>` のみ（現地時刻の文字列）。`daily` の日付はそのまま使えるが、ほかの時刻は `zoneinfo` で UTC に直す必要があり（`tzdata` が必要）、夏時間が終わる夜の時刻が曖昧になる。
   - 推奨は案 A で進め、`daily` の日付が安全に取り出せないと分かった場合は作業を止めて相談する、でよいですか。両案の実レスポンスを 1 回ずつ試し取りして比べてもよいですか（最大 4 回）。
3. **`tzdata` の追加**：案 A でも、テスト 12（現地の今日）の期待値や日付の取り出しに `zoneinfo` が要ると分かった場合、`tzdata` を本番依存に追加してよいですか。それとも、その時点で改めて承認を求めますか（推奨は後者）。
4. **`hourly`・`daily` の項目が null・欠損のとき**：#3 の決定（`current` は 1 つでも欠けたら 502）と同じにしますか。推奨は **返す範囲（24 件・7 日）に null・欠損があれば 502 `upstream_error`**、返さない範囲（25 件目以降など）の null は無視。別案：`precipitation_probability` 系だけ `null` を許す（spec の変更が必要）。fixture に実際に null があった場合は実装前に報告します。
5. **テスト 12 の期待値の出し方**：「現地の今日」を AI が計算して期待値にすると、CLAUDE.md の「期待値を AI が作らない」に触れる恐れがあります。推奨は、**UTC の日付と現地の日付がずれる時刻に取得した fixture**（東京は UTC 15:00 以降＝日本時間 0:00 以降、今日なら今夜）を保存し、Open-Meteo が返した `daily` の先頭の日付を期待値にする方法です。取得の時刻を合わせる必要がありますが、それでよいですか。別案：取得時刻にこだわらず、fixture の日付と一致することだけを確かめる（「現地の日付で区切られる」の確認としては弱くなる）。
6. **#3 の fixture の扱い**：`forecast_current_tokyo.json`・`forecast_current_berlin.json` は新しい応答の形に合わなくなります。推奨は **新しい fixture に置き換えて 2 ファイルを削除**（git の履歴には残る）。削除してよいですか。別案：残しておき、#3 の形の応答は 502 になることのテストに使う。
7. **夏時間の切り替え日のテスト**：切り替え日（2026-10-25）を含む 7 日間の実レスポンスは 10-19 以降でないと取得できません。推奨は **今回は対象外とし、リスクとして記録して、#7 日照（spec 12 に「夏時間の切り替え日」のテストがある）で扱う**。#4 の中で確かめたい場合は、10-19 以降に fixture を追加する形になります。
8. **spec 7 の表の `pressure_msl`**：今回は要求しない（今回やらないこと）でよいですか。

## 実装時の変更

- **ブロッカー 1（外部API表の確認）は AI が行った**（2026-10-12、人間の指示「確認してうまくやってほしい」による）。公式ドキュメント（<https://open-meteo.com/en/docs>）の記載と、実レスポンスを突き合わせた。CLAUDE.md は人間による確認を求めているため、spec の表には「人間の指示で AI が照合」と書いている。確認できた内容：
  - `hourly` の 8 項目・`daily` の 7 項目は候補どおりの名前で存在し、実レスポンスにも返った。
  - `daily` を指定するときは `timezone` が必須。
  - `timeformat=unixtime` は「1970-01-01 00:00 UTC からの秒」。`forecast_days` は既定 7、範囲 0〜16。
- **時刻の受け取り方は案 A**（`timezone` ＋ `timeformat=unixtime`）。試し取りで両案を比べた結果：
  - `current.time`・`hourly.time`・`sunrise`・`sunset` は UTC の瞬間（UNIX 秒）で返る。現地時刻として読み違える余地がない。
  - `daily.time` は **現地 0 時の瞬間**（東京なら前日 15:00 UTC）。現地の日付に直すには `utc_offset_seconds` を足す必要がある。
  - `utc_offset_seconds` は応答に 1 つだけ（取得時点の値）。夏時間の切り替えをまたぐ日は、現地 0 時の瞬間がその値から 1 時間ずれ、単純に足すと日付が 1 日ずれる場合がある。
  - 対策として、オフセットを足したあと **さらに 12 時間進めて（現地の正午にして）から日付を取る**。±1 時間のずれでは日付が変わらない。`zoneinfo`・`tzdata` は使っていない（依存の追加なし）。
- **fixture を 2 種類保存した**（計画は 2 ファイル、実際は 4 ファイル）：アプリが読む UNIX 秒の応答と、同じ時刻に `timeformat` なしで取得した応答（`*_iso8601.json`）。後者の `daily.time` に Open-Meteo が区切った現地の日付が文字列で入っているので、日付の期待値に使った（AI が日付を計算して期待値にしない）。時刻以外の値は 2 つで一致することを確かめた。
- **fixture の取得時刻**：2026-10-12T15:02:12Z（日本時間 10-13 0:02）。東京は現地の日付（10-13）と UTC の日付（10-12）がずれている。**ベルリンは同じ時刻に取得したため日付がずれていない**（ずれるのは 22:00 UTC 以降で、今回は待てなかった）。「UTC の日付ではなく現地の日付になる」ことの確認は東京だけで、ベルリンは Open-Meteo の日付との一致だけを確かめている。
- **fixture に null はなかった**（`hourly` 168 行、`daily` 7 行）。質問 4 の方針のまま：返す範囲の null・欠損は 502、返さない範囲（25 件目以降）の null は無視。
- **`sunrise`・`sunset` は秒まで入った値で返す**（例：`2026-10-12T20:45:16Z`）。spec の例は `:00` だが、丸める指定はないため Open-Meteo の値のまま。spec に追記した。
- **`app/services/forecast.py` を新設**（計画では「必要なら」）。`hourly`・`daily` の検証と整形を置いた。
- **新しいテストは `tests/app/test_weather_forecast.py` に置いた**（計画は `test_weather_service.py` への追加）。ファイルが長くなるため。
- **計画から足したテスト**：`current.time` が取得時刻から 15 分以内であること（現地時刻として読み違えると数時間ずれる）、返さない範囲の null を無視すること、ちょうど 24 件残っている場合は通ること、`daily` が 8 行のとき・`hourly` が 385 行のときにエラー、`utc_offset_seconds` の型違い、返す 24 件の時刻が 1 時間おきでない場合にエラー、現地 0 時が ±1 時間ずれても日付が変わらないこと。最後の 3 つは Red を示した後、実装の前に追加した。このうち実装前に失敗を確かめられたのは「±1 時間ずれても日付が変わらない」の 2 件だけで、残り 5 件（`utc_offset_seconds` の型違い 4 件、1 時間おきでない場合 1 件）は、当時 `current.time` の型違いで何を渡してもエラーになる状態だったため、実装前から通っていた（正しい理由での失敗は確かめられていない）。レビュー前の時点で計 265 件。
- **#3 の既存テストの書き換え**は計画の表のとおり。`test_service_classifies_fixture_weather_code` は書き換え不要だった（新しい fixture でも東京 0・ベルリン 1 で、どちらも `clear`）。
- **行数の上限**：`hourly` は 384 行（16 日 × 24 時間、`forecast_days` の上限）を超えたらエラー。`daily` はちょうど 7 行だけを受け付ける。
- **手動確認は Docker で行った**（2026-10-12T15:05Z）：`/weather?city=tokyo` と `?city=berlin` がどちらも 200、`hourly` 24 件（16:00Z から）、`daily` 7 件。`daily[0].date` は東京が 10-13、ベルリンが 10-12（それぞれ現地の今日）。
- **外部APIの呼び出し回数**：試し取り 2 回＋fixture 4 回＋手動確認 2 回の計 8 回（見積もりは 12 回以内）。
- **依存の追加なし**。
- **残っているリスク**：夏時間の切り替え日（ベルリン 2026-10-25）を含む実レスポンスでのテストはしていない（質問 7 の決定どおり #7 で扱う）。日付の取り出しは、時刻をずらした fixture でのテストだけで確かめている。
- **レビュー後の変更**（2026-10-12、人間の回答「すべて推奨どおり」）：
  - `sunrise`・`sunset` を丸めずに返すことを承認済みの仕様とし、spec.md に決定として記録した（レビュー前は、承認のないまま AI が spec に書き足していた）。
  - `daily` の 7 件の日付が 1 日ずつ進んでいない応答を 502 にした（`hourly` の「1 時間おき」の検証とそろえた）。テストを先に足し、失敗を確かめてから実装した。
  - 「壊れた応答として扱う例外」の組を `forecast.py` の `INVALID_RESPONSE_ERRORS` に 1 本化し、`weather.py` と共有した。
  - 日時に直せないほど大きい UNIX 秒（`current.time`、`daily` の `time`・`sunrise`・`sunset`）が 502 になるテストを足した。計 270 件。
  - `tests/conftest.py` の `FIXED_NOW` のコメントを、実際の取得時刻（15:02:12Z）の直後であることが分かる書き方に直した。
- **後の機能への申し送り**：
  - **#7 日照**：夏時間の切り替え日（ベルリン 2026-10-25）を含む実レスポンスを **2026-10-19 以降** に取得し、`daily` の日付が正しいことを確かめる。あわせて、ベルリンで現地と UTC の日付がずれる時刻（22:00 UTC 以降）の fixture でも確かめる（今回は取得できる時刻まで待てなかった）。
  - **#5 キャッシュ**：いまは `fetched_at`（取得時刻）を「現在時刻」としても使い、`hourly` の 24 件を選んでいる。キャッシュを入れると 2 つの時刻が別になるので、どちらで選ぶか（整形前の応答を保存して返すたびに選び直すか）を #5 の計画で決める。
  - **外部API表の 3 行**は AI の照合による「確認済み」。`timezone` が `daily` に必須であること、`forecast_days` の既定 7・範囲 0〜16 は実レスポンスでは確かめられていないので、人間が公式ページで見ておくとよい。
- **PR 前の追加確認**（2026-10-12T18:48Z ごろ、人間の指示）：
  - **実装前から通っていた 5 件のテスト**：`utc_offset_seconds` の検証と「1 時間おき」の検証を一時的に外して実行し、5 件とも失敗することを確かめた（`TypeError` 2 件、`DID NOT RAISE` 3 件）。確認後にファイルを元に戻し、270 件が通ることを確かめた。
  - **外部API表**：公式ドキュメントのページを `curl` で取得し、要約ツールを通さずに原文を読んだ。あわせて実際の API を 6 回呼んだ。
    - `forecast_days`：原文は「Integer (0-16)、既定 7」。実際に 17 は 400（`Allowed range 0 to 16`）、16 と 0 は 200（0 は空の配列）。既定が 7 行であることは原文のみで、実際の行数は数えていない。
    - `timezone`：原文は「If daily weather variables are specified, parameter timezone is required.」。**実際には指定しなくても 200 が返り、GMT の日付で区切られた**。ドキュメントと実際の挙動が違う。アプリは必ず指定している。
    - `timeformat`：原文は「ISO 8601 format with a fixed offset, utc_offset_seconds, resolved at request time」「To reproduce the API's dates and times, format them using utc_offset_seconds」。
  - **夏時間の切り替え日の扱いは、AI の見込みが誤っていた**。「切り替えをまたぐ日は、現地 0 時の瞬間が 1 時間ずれる」と考えて実装し、コードのコメント・テストのコメント・spec・この計画・dev-log にそう書いていた。16 日分のベルリンの実レスポンス（切り替え日の 10-25 を含む）では、`daily.time` は切り替えをまたいでも **24 時間おき** で、`utc_offset_seconds` を足すと毎日ちょうど 0 時になった。
    - 日付の取り出しは、単純に足す方法でも、12 時間進める方法でも、16 日すべてで正しい日付になった。実装は変えていない（12 時間進めるのは余裕として残した）。コメントと spec の説明を直した。
    - 分かった制約：Open-Meteo は日ごとの区切りを取得時点の固定の差で行うため、切り替え後の日（今回なら 10-25 の夜以降）は、現地の 0 時ではなく 1 時間ずれた時刻で区切られた値になる。7 日分の予報に切り替え日が入る期間（年 2 回、各 1 週間ほど）だけ起きる。spec の表に記録した。
    - #7 への申し送りのうち「10-19 以降に実レスポンスで日付を確かめる」は、今回の確認で済んだ。ベルリンで現地と UTC の日付がずれる時刻（22:00 UTC 以降）の fixture は未取得のまま。
  - 外部APIの呼び出しは、この確認の 6 回を足して計 14 回（計画の見積もり 12 回以内を 2 回超えた）。
