# 仕様書（spec.md）

最終更新：2026-10-13　／　状態：初版（天気予報の拡張・日照計算を追加。#4 で時間・日ごとの予報の仕様を確定。#5 でキャッシュの仕様を確定。#6 でリトライと stale の仕様を確定。#7 で日照の仕様を確定。#8 でデータ取得の仕様を確定。#9 で目的変数と学習データの期間を確定）

## 1. 目的

- 外部天気APIを呼び、必要な項目だけ整形して返すAPIを作る（外部API連携・キャッシュの学習）
- 空港観測データから **雲底高度（シーリング）** を予測するモデルを作り、APIから提供する
- Docker・CI/CD・定期実行による Discord 通知までを 1 リポジトリで完結させる
- Claude Code を使った開発過程（プロンプト、コンテキスト、コスト、誤り対策、評価）を記録し、説明できるようにする

## 2. スコープ

**対象**：天気取得API、キャッシュ、雲底高度予測（データ取得・EDA・学習・評価・推論）、Discord通知、CI/CD、Docker

**対象外**：ユーザー認証、クラウドへの本番デプロイ、東京・ベルリン以外の地点（将来拡張）

## 3. 対象地点

| city（APIの値） | 空港 | ICAO | 緯度・経度（概算） | タイムゾーン |
|---|---|---|---|---|
| `tokyo` | 羽田空港 | RJTT | 35.55, 139.78 | Asia/Tokyo |
| `berlin` | ベルリン・ブランデンブルク空港 | EDDB | 52.36, 13.50 | Europe/Berlin |

`city` はこの許可リスト以外を受け付けない。
日単位のデータ（日ごとの予報・日の出入り・暗い時間）は、その都市の **現地の日付** で区切る。

## 4. システム構成

```
[Open-Meteo] ──> app/clients ──> app/services ──> app/routers ──> クライアント
                      │                │
                   [Redis キャッシュ]   ├── ml/features.py + models/ ──> /cloud-base
                                        └── app/services/solar.py（計算のみ）──> /daylight
[METAR (IEM)] + [Open-Meteo 過去] ──> notebooks/01〜05 ──> models/, reports/
GitHub Actions（schedule）──> コンテナ実行 ──> Discord Webhook
```

## 5. API仕様

### 共通

- レスポンスは JSON。時刻は ISO 8601（UTC、末尾 `Z`）。日付は現地の日付（`YYYY-MM-DD`）。
- エラー形式：`{"error": {"code": "<文字列>", "message": "<説明>"}}`

| HTTP | code | 条件 |
|---|---|---|
| 422 | `invalid_city` | 許可リスト外の city |
| 422 | `invalid_date` | 日付の形式が不正、または範囲外 |
| 502 | `upstream_error` | 外部APIの失敗かつ使えるキャッシュがない |
| 503 | `model_unavailable` | モデルファイルが読み込めない |

### `GET /health`

`{"status": "ok"}` を返す。

### API ドキュメント（自動生成）

FastAPI が自動で生成する `/docs`（Swagger UI）、`/redoc`、`/openapi.json` を公開する。
開発中の動作確認に使うためで、内容はコードから生成される（手で書かない）。

### `GET /weather?city=tokyo`

天気アプリとして使えるよう、現在・24時間（1時間ごと）・7日間（日ごと）を返す。

```json
{
  "city": "tokyo",
  "timezone": "Asia/Tokyo",
  "current": {
    "time": "2026-10-12T03:00:00Z",
    "weather_code": 2,
    "weather": "partly_cloudy",
    "temperature_c": 21.3,
    "apparent_temperature_c": 21.0,
    "dew_point_c": 15.2,
    "relative_humidity": 68,
    "precipitation_mm": 0.0,
    "wind_speed_ms": 3.4,
    "cloud_cover": {"total": 50, "low": 40, "mid": 10, "high": 0}
  },
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
  ],
  "source": "open-meteo",
  "fetched_at": "2026-10-12T02:55:00Z",
  "cached": true,
  "stale": false
}
```

- `hourly` は現在時刻以降の 24 件、`daily` は今日から 7 日分。
  - `hourly` の先頭は、現在より後の最初の正時（現在が 13:41 なら 14:00。現在が正時ちょうどならその時刻を含む。2026-10-12 決定）。
  - `daily` の「今日」と日付の区切りは現地の日付。`sunrise`・`sunset` は Open-Meteo の値を丸めずに UTC で返す（秒まで入る。上の例は `:00` だが、分単位に丸めない。2026-10-12 決定）。
  - 返す範囲（24 件・7 日）の項目が Open-Meteo の応答に欠けている・null の場合、件数が足りない場合は 502 `upstream_error`（一部だけ返さない。2026-10-12 決定）。
- `city` を省略した場合は `tokyo` として扱う（2026-10-12 決定。使い始めやすくするため）。空文字（`city=`）は省略とは扱わず 422 `invalid_city`。
- `current` の項目が Open-Meteo の応答に欠けている・null の場合は 502 `upstream_error`（一部だけ null で返さない。2026-10-12 決定）。
- 機能ごとに段階的に追加する：#3 で `city`・`timezone`・`current`・`source`・`fetched_at`、#4 で `hourly`・`daily`、#5 で `cached`、#6 で `stale`（2026-10-12 決定）。未実装のキーは返さない。
- `cached` は、キャッシュの値を返したとき `true`、外部APIから取得した値を返したとき `false`（#6 で「外部APIを呼ばずに」から書き直した。stale のときは外部APIを呼んだうえでキャッシュの値を返すため）。
  - キャッシュから返すときも、`fetched_at` は外部APIから取得した時刻のまま。`hourly` の 24 件は、返すたびにその時刻で選び直す（過ぎた時刻を先頭に残さない。2026-10-12 決定）。
- `stale` は、外部APIが失敗し、TTL を過ぎた保存値を返したとき `true`。このとき `cached` も `true`。それ以外は常に `false`（2026-10-12 決定、#6）。
  - stale のときも `hourly` はその時刻で選び直す。`daily` は選び直さず、取得した日から 7 日分をそのまま返す（取得後に現地の日付が変わると、先頭が「昨日」になる。別の Issue で扱う。2026-10-12 決定）。
- 上の数値は形式を示す例で、実在の観測値ではない。

**天気の分類（`weather`）**

Open-Meteo の天気コード（WMO の天気コード）を、アプリで扱いやすい分類に変換する。
対応表は `app/services/weather_codes.py` に実装している（2026-10-12 に公式ドキュメントの天気コード表を人間が確認し、分類を決定）。

| weather | 意味 | 天気コード（Open-Meteo の説明） |
|---|---|---|
| `clear` | 快晴 | 0（Clear sky）、1（Mainly clear） |
| `partly_cloudy` | 晴れ時々曇り | 2（Partly cloudy） |
| `cloudy` | 曇り | 3（Overcast） |
| `fog` | 霧 | 45（Fog）、48（Depositing rime fog） |
| `drizzle` | 霧雨 | 51・53・55（Drizzle）、56・57（Freezing drizzle） |
| `rain` | 雨 | 61・63・65（Rain）、66・67（Freezing rain）、80・81・82（Rain showers） |
| `snow` | 雪 | 71・73・75（Snowfall）、77（Snow grains）、85・86（Snow showers） |
| `thunderstorm` | 雷雨 | 95（Thunderstorm）、96・99（Thunderstorm with hail） |
| `unknown` | 対応表にないコード（エラーにせずこれを返し、ログに残す） | 上記以外 |

### `GET /daylight?city=berlin&date=2026-12-21`

日の出・日の入りと薄明、昼の長さ・暗い時間を返す。外部APIは使わず、太陽位置の計算で求める。
`date` は省略時に現地の今日。範囲は 1900-01-01〜2100-12-31。

```json
{
  "city": "berlin",
  "date": "2026-12-21",
  "sunrise": "2026-12-21T07:15:00Z",
  "sunset": "2026-12-21T14:55:00Z",
  "twilight": {
    "civil":        {"dawn": "...", "dusk": "..."},
    "nautical":     {"dawn": "...", "dusk": "..."},
    "astronomical": {"dawn": "...", "dusk": "..."}
  },
  "daylight_hours": 7.67,
  "night_hours": 16.33,
  "dark_hours": 15.0,
  "solar_noon": "2026-12-21T11:05:00Z",
  "solar_noon_elevation_deg": 14.2,
  "method": "noaa-solar-calculator"
}
```

**用語の定義**

| 項目 | 定義（太陽の高度） |
|---|---|
| sunrise / sunset | 太陽の上端が地平線にかかる時刻（大気差を考慮し、中心高度 −0.833°） |
| civil（市民薄明） | −6° |
| nautical（航海薄明） | −12° |
| astronomical（天文薄明） | −18° |
| `daylight_hours` | 日の出から日の入りまで |
| `night_hours` | 24 − `daylight_hours` |
| `dark_hours` | 太陽が −6° より下にある時間（市民薄明が終わってから始まるまで）。「明かりなしでは暗い」時間として扱う |

**境界のケース**

- 高緯度の夏は、太陽が一晩中 −18° まで沈まない日がある（ベルリンでは夏至前後に天文薄明が終わらない）。
  その場合、該当する `dawn` / `dusk` は `null` とし、レスポンスにエラーは出さない。
- 一日中その高度より上・下にある場合も `null`（白夜・極夜。対象2都市では日の出入り自体は毎日あるが、計算関数としては扱う）。
- 夏時間の切り替え日でも、時刻は UTC で返すため影響を受けない。日付の区切りは現地時間。

**精度**：Open-Meteo の `sunrise` / `sunset` と比べて ±2 分以内（テストで確認）。

**#7 で決めたこと（2026-10-12）**

- `city` を省略した場合は `tokyo`（`/weather` と同じ）。空文字は 422 `invalid_city`。
- `date` は半角数字の `YYYY-MM-DD` だけを受け付ける。それ以外の書き方、実在しない日付、空文字、範囲外は 422 `invalid_date`。
- `city` と `date` の両方が不正なときは `invalid_city`（code は 1 つだけ返す）。
- 時刻は秒まで返す（秒未満は四捨五入。分には丸めない）。
- 「その日の」朝・夕は、その現地日付の **南中を基準** に、前の通過を朝（`sunrise`・`dawn`）、後の通過を夕（`sunset`・`dusk`）とする。夕方の薄明の終わりが現地の 0 時を過ぎる日（ベルリンの初夏の天文薄明など）も、その日の `dusk` として返す。
- `daylight_hours` は応答の `sunrise` から `sunset` まで、`dark_hours` は 24 −（その日の civil の `dawn` から `dusk` まで）。どちらも小数 2 桁。夏時間の切り替え日（現地の 1 日が 23・25 時間）でも 24 から引く。
- 太陽がその高度を通らない日は、ずっと上なら `daylight_hours: 24.0`・`dark_hours: 0.0`、ずっと下なら `0.0`・`24.0`。`sunrise`・`sunset` も `null` になりうる型にしている（対象 2 都市では起きない）。
- `solar_noon_elevation_deg` は大気差の補正を入れない高度で、小数 1 桁。
- 計算は NOAA のスプレッドシート（NOAA_Solar_Calculations_day）の式。薄明は、日の出の時角の式の高度（−0.833°）を −6°・−12°・−18° に替えて求める（この置き換えは NOAA の資料にはない）。
- 上の JSON の数値は形式を示す例で、実際の計算結果ではない。

### `GET /cloud-base?city=tokyo`

```json
{
  "city": "tokyo",
  "valid_at": "2026-10-12T03:00:00Z",
  "predicted_m": 850,
  "baseline_m": 760,
  "model_version": "2026-10-xx-lgbm-v1"
}
```

`baseline_m` は概算式 `125 × (気温 − 露点)` による値。

## 6. キャッシュ

- キー：`weather:{city}`、TTL：15分（現在・時間ごと・日ごとを 1 回の外部呼び出しでまとめて取得し、まとめてキャッシュする）
- `/daylight` は計算のみで外部通信がないため、キャッシュしない。
- 外部API失敗時は、最大6時間前までのキャッシュを `stale: true` で返す。それより古ければ 502。
- 開発初期はメモリキャッシュ、その後 Redis（docker compose）に切り替える。インターフェースは共通化する。

**#5 で決めたこと（2026-10-12）**

- 保存するのは整形前の Open-Meteo の応答と取得時刻（JSON の文字列）。整形に成功した応答だけを保存し、失敗や壊れた応答は保存しない。
- TTL の境界：取得から 15 分未満なら使う。ちょうど 15 分から外部APIを呼び直す。
- 保存値が読めない・形が違う・取得時刻が未来・いまの時刻では整形できない場合は、キャッシュなしとして外部APIを呼び直す。
- キャッシュが故障したとき（Redis に接続できないなど）は、キャッシュなしとして外部APIを呼び、200 を返す（警告ログを残す）。
- 同時に来たリクエストを 1 回の外部呼び出しにまとめる仕組みは入れていない（キャッシュが空・期限切れの瞬間に重なると、その数だけ外部APIを呼ぶ）。
- 設定（環境変数）：

| 変数 | 既定値 | 内容 |
|---|---|---|
| `CACHE_BACKEND` | `memory` | 保存先。`memory` または `redis`（`docker-compose.yml` では `redis`） |
| `CACHE_TTL_S` | `900` | TTL（秒） |
| `REDIS_URL` | なし | Redis の接続先。`CACHE_BACKEND=redis` のとき必須。パスワードを含みうるのでシークレットとして扱う |
| `REDIS_TIMEOUT_S` | `1` | Redis の接続・読み書きのタイムアウト（秒） |

**#6 で決めたこと（2026-10-12）**

- stale を返すのは、外部APIの呼び出しが `upstream_error` になる場合すべて（リトライを使い切った失敗、4xx、JSON でない応答、項目の欠けた応答）。
- 上限の境界：取得からちょうど 6 時間は返す。6 時間を過ぎたら 502。
- stale のときは `cached: true`・`stale: true`。`fetched_at` は外部APIから取得した時刻のまま。
- 設定（環境変数）：

| 変数 | 既定値 | 内容 |
|---|---|---|
| `CACHE_STALE_MAX_AGE_S` | `21600` | stale として返してよい上限（秒）。`CACHE_TTL_S` 以上（それより短いと起動時に検証エラー。2026-10-12 のレビューで決定） |

## 7. 外部API・データ

**実装前に公式ドキュメントで確認し、「状態」を更新すること。未確認の項目は使わない。**

| 用途 | 提供元 | エンドポイント・項目（候補） | 利用条件・制限 | 状態 |
|---|---|---|---|---|
| 予報（現在） | Open-Meteo Forecast | `api.open-meteo.com/v1/forecast`、`current=` に temperature_2m, apparent_temperature, dew_point_2m, relative_humidity_2m, precipitation, weather_code, cloud_cover, cloud_cover_low/mid/high, wind_speed_10m。応答の `current.time` は UTC（`timezone` 未指定時、オフセットなしの ISO 8601） | 無料の API は非商用のみ。上限 600 回/分・5,000 回/時・10,000 回/日・300,000 回/月。API キー不要。データは CC BY 4.0（表示する場所に出典のリンクが必要） | 確認済み（2026-10-12、#3） |
| 予報（時間） | Open-Meteo Forecast | 同上、`hourly=` に temperature_2m, precipitation_probability, precipitation, weather_code, cloud_cover, cloud_cover_low/mid/high。応答は列ごとの配列（7 日分で 168 行、現地の今日 0 時から）。pressure_msl は未使用・未確認（#12 で確認する） | 同上 | 確認済み（2026-10-12、#4。人間の指示で AI が公式ドキュメントと実レスポンスを照合） |
| 予報（日ごと） | Open-Meteo Forecast | 同上、`daily=` に weather_code, temperature_2m_max/min, precipitation_sum, precipitation_probability_max, sunrise, sunset。公式ドキュメントは「`daily` を指定するときは `timezone` が必須」としている（実際には指定しなくても 200 が返り、GMT の日付で区切られた。必ず指定する） | 同上 | 確認済み（2026-10-12、#4。同上） |
| 予報のオプション（風速の単位） | Open-Meteo Forecast | `wind_speed_unit=ms`（既定は km/h） | 同上 | 確認済み（2026-10-12、#3） |
| 予報のオプション（その他） | Open-Meteo Forecast | `timezone=<IANA の名前>`（既定は GMT。日ごとの値がそのタイムゾーンの日付で区切られる）、`timeformat=unixtime`（既定は iso8601。時刻が UTC の UNIX 秒になる。`daily.time` に `utc_offset_seconds` を足すと日付になる。`utc_offset_seconds` は取得時点の UTC との差で、応答全体に 1 つだけ。日ごとの区切りもこの固定の差で行われ、夏時間の切り替えをまたいでも 24 時間おき＝切り替え後の日は現地の 0 時から 1 時間ずれた区切りになる）、`forecast_days=7`（既定 7、範囲 0〜16。17 は 400、0 は空の配列） | 同上 | 確認済み（2026-10-12、#4。同上） |
| 天気コード表 | Open-Meteo / WMO | weather_code の各値の意味（「天気の分類」の表を参照） | — | 確認済み（2026-10-12、#3） |
| 予報のオプション（日付の指定） | Open-Meteo Forecast | `start_date`・`end_date`（`yyyy-mm-dd`）。指定できる範囲は公式ドキュメントに書かれていない。2026-10-12 時点の実レスポンスでは 2026-07-11〜2026-10-27（それ以外は 400）。アプリでは使っていない | 同上 | 確認済み（2026-10-12、#7。人間の指示で AI が公式ドキュメントと実レスポンスを照合） |
| 太陽位置の計算式 | NOAA Solar Calculator | `gml.noaa.gov/grad/solcalc/`。スプレッドシート（NOAA_Solar_Calculations_day）の各列の式（Jean Meeus『Astronomical Algorithms』による）。日の出入りの大気差は 0.833° と仮定。日の出入りは緯度 ±72° の内側で「理論上 1 分以内」。近似がよいのは 1800〜2100 年。薄明の式はない。**アプリからは通信しない**（式の出典と、テストの期待値＝スプレッドシートに入っている計算済みの値） | — | 確認済み（2026-10-12、#7。同上） |
| 薄明・南中の期待値（テスト用） | 米国海軍天文台（USNO） | `aa.usno.navy.mil`。定義は日の出入りが天頂角 90.8333°、薄明が 6°・12°・18°（spec と同じ）。1 年ぶんの表（`/calculated/rstt/year`、`task` は 2＝市民・3＝航海・4＝天文）と 1 日ぶんのAPI（`/api/rstt/oneday`。市民薄明・日の出入り・南中）。どちらも分単位。**アプリからは通信しない**（fixture の取得だけ） | 利用の制限は書かれていない | 確認済み（2026-10-12、#7。同上） |
| 過去の気象 | Open-Meteo Historical | `archive-api.open-meteo.com/v1/archive`、`start_date`・`end_date`（必須、`yyyy-mm-dd`）。`hourly=` に temperature_2m, dew_point_2m, relative_humidity_2m, pressure_msl, precipitation, weather_code, cloud_cover, cloud_cover_low/mid/high, wind_speed_10m（precipitation だけ「前の 1 時間の合計」、ほかは「その時刻の値」）。`wind_speed_unit=ms`、`timeformat=unixtime`、`timezone` の既定は GMT。`daily=` に sunrise, sunset（#7 のテストの期待値として取得）。データは再解析（ERA5 など。1940 年〜、5 日遅れ） | 非商用は API キー不要。上限は予報と同じ（600 回/分・5,000 回/時・10,000 回/日・300,000 回/月）。10 項目を超える・2 週間を超える要求は、複数回ぶんとして数えられる（式は公式に書かれていない） | 確認済み（2026-10-12、#8。人間の指示で AI が公式ドキュメントと実レスポンスを照合） |
| METAR過去データ | Iowa Environmental Mesonet（IEM） | `mesonet.agron.iastate.edu/cgi-bin/request/asos.py`。`station`（ICAO）、`data`（列。複数可）、`sts`・`ets`（開始を含み、終了を含まない）、`tz=UTC`、`format=onlycomma`、`missing=empty`、`trace=empty`、`report_type`（3＝定時、4＝臨時）。列：valid（観測の時刻）、tmpf・dwpf（華氏）、vsby（マイル）、skyc1〜4（雲の層の量）、skyl1〜4（雲の層の高さ、フィート）、wxcodes、metar（もとの電文）。mslp は対象の 2 空港では空 | パブリックドメイン（IEM の名前を書くことが望ましい）。同じ IP からは 1 秒に 1 回まで（超えると 429）、混雑時は 503、1 回の要求は 1,000 観測所・年まで（超えると 422） | 確認済み（2026-10-12、#8。人間の指示で AI が公式ドキュメントと実レスポンスを照合） |

- 外部通信のタイムアウト：接続 3 秒、全体 10 秒。リトライは最大 2 回（指数バックオフ）。
  - 「全体 10 秒」は 1 回の試行ごと（2026-10-12 決定、#6）。
  - 「最大 2 回」は、最初の 1 回に加えて 2 回（合計で最大 3 回）。待ち時間は 0.5 秒 → 1.0 秒（基準を 2 倍ずつ。ゆらぎなし）。
  - リトライするのは、タイムアウト・接続エラー（途中で切れた接続を含む）・5xx だけ。4xx（429 を含む）と、壊れた応答（JSON でない、圧縮が壊れているなど）はリトライしない。
  - 設定（環境変数）：`OPEN_METEO_MAX_RETRIES`（既定 `2`、範囲 0〜5。上限は 2026-10-12 のレビューで決定）、`OPEN_METEO_RETRY_BACKOFF_S`（既定 `0.5`）。
- 通信先は上表のホストのみ。NOAA と USNO は、開発時に資料と fixture を取得しただけで、アプリからは通信しない。
- 学習データの一括取得（`notebooks/01_data_fetch`。#8、2026-10-12 決定）は、1 年ぶんをまとめて取るので、全体のタイムアウトを別に持つ。接続 3 秒とリトライの決まりは上と同じ。
  - IEM を続けて呼ぶときは、間を 2 秒あける（並列にしない）。429 はリトライせず、そこで止まる（取得済みの年は保存してあるので、やり直すと続きから進む）。
  - 設定（環境変数）：`DATA_FETCH_TIMEOUT_S`（既定 `60`。試行ごと）、`IEM_REQUEST_INTERVAL_S`（既定 `2`、1 未満は不可）、`IEM_BASE_URL`（既定 `https://mesonet.agron.iastate.edu`）、`OPEN_METEO_ARCHIVE_BASE_URL`（既定 `https://archive-api.open-meteo.com`）。

## 8. Discord 通知

- 毎朝 07:00（JST）に、東京・ベルリンの次の内容を送る：
  今日の天気・最高/最低気温・降水確率、日の出・日の入り、昼の長さと暗い時間、雲底高度予測。
- GitHub Actions の schedule でコンテナを実行する。
- Webhook URL は GitHub Secrets（`DISCORD_WEBHOOK_URL`）に保存し、ログに出さない。
- 送信失敗時はジョブを失敗させ、Actions 上で気づけるようにする。

## 9. 雲底高度予測（ML）

### 目的変数

- METAR の最も低い BKN または OVC 層の高さ（シーリング）をメートルに変換した値。

**#9（EDA）で決めたこと（2026-10-13。根拠は `docs/eda.md`）**

- **シーリングなし（雲が少ない・ない）は、上限で打ち切る**。上限は 1,524 m（5,000 フィート）。目的変数 ＝ `min(シーリング, 1524)`。BKN・OVC の層がない正時（FEW・SCT・NSC・NCD だけ、または `CAVOK` などで雲の層の報告がない）は 1,524 m とする。「分類と回帰に分ける」は採らない。
  - 理由：ベルリンは 1,500 m より高いシーリングをほとんど報告していない（学習期間で 96.35% が 1,500 m 以下）。2 都市で同じ意味になる上限にする。
  - 上限の行が多い（学習期間で「雲が少ない・ない」が東京 41.31%・ベルリン 68.84%）ので、評価では全体の MAE に加えて、上限より下の行だけの MAE と、「上限より下にあるか」の当たり外れも出す（評価関数は #10）。
- **高さのない BKN・OVC の層（電文の `BKN///`）は、飛ばして次の層を見る**（#8 のまま）。飛ばした層は、全期間の 1,668 件すべてで、値を決めた層より上にあった（値は変わらない）。
- **BKN・OVC があるのに、どの層にも高さがない正時は、学習・評価から除く**（正解が分からない。全期間で東京 11,397・ベルリン 16）。
- **`VV`（鉛直視程）は、高さがあればシーリングとして数える（その高さ）。高さのない `VV///` は学習・評価から除く**（全期間で、高さあり 161・なし 68）。雲の量の列には末尾に空白の付いた `VV ` で入っているので、空白を取って比べる。
- **METAR が付かなかった正時は、学習・評価から除く**（全期間で 13）。
- `data/processed/observations.parquet` の `ceiling_m` は #8 の定義のまま。

**#10 で決めたこと（2026-10-13）**

- 目的変数は `ml/target.py` の `target_m` で、読み込んだ表にその場で付ける（列の名前は `target_m`。parquet には保存しない）。学習・評価から除く行は欠損。03・04・05 は同じ関数を使う。
- 作り方：BKN・OVC・`VV` のうち高さのある層の、最も低い高さと 1,524 の小さいほう。それらの層があるのにどれにも高さがなければ欠損。それらの層がなければ 1,524。METAR が付いていなければ欠損。
  - `VV` と BKN・OVC が同じ正時にある場合は、3 種類のうち最も低い高さになる（全期間のデータでは 0 件）。
- `CAVOK`・`NSC`・`VV`・`BKN///` の意味は、WMO のハンドブック（WMO-No. 782、2025 年版）と照合した（`docs/eda.md`「公式の資料での確認」）。`CAVOK`・`NSC` の基準は「1,500 m（5,000 ft）または最低扇形別高度の最も高いもののうち、大きいほうより下に雲がない」。`NCD`（自動観測で雲が検出されなかった）には高さの基準が書かれていないが、`NSC` と同じく 1,524 m とする。

### 特徴量（候補）

気温、露点、気温と露点の差、相対湿度、海面気圧、風速、層別雲量、時刻・季節（周期表現）、太陽高度（`app/services/solar.py` の計算を共有）、都市。

### ベースライン

`125 × (気温 − 露点)` [m]。モデルはこれに勝つことが前提。

**#10 で決めたこと（2026-10-13。数値は `reports/baseline.json`）**

- 入力は Open-Meteo の気温・露点（API の `baseline_m` と同じ）。値は目的変数と同じ範囲（0〜1,524 m）に収める（露点差が負なら 0、上限を超えたら 1,524）。`ml/baseline.py` の `baseline_m`。
  - これは評価のときの範囲。API の応答（`/cloud-base` の `baseline_m`）で同じ範囲に収めるかどうかは #12 で決める。
- 参考として、同じ表に 2 つ並べる：「いつも上限（1,524 m）と答える」、「METAR の気温・露点で計算した概算式」。
- #10 で評価したのは学習（2018〜2023）と検証（2024）の年だけ。テストの年（2025）のベースラインは、#11 の `05_evaluate` で同じ関数を使って出す。
- 結果（MAE、m）：

| 分割 | 都市 | 全体：概算式 | 全体：いつも上限 | 上限より下の行：概算式 | 上限より下の行：いつも上限 |
|---|---|---|---|---|---|
| 学習 2018〜2023 | 東京 | 725.63 | 230.74 | 364.74 | 835.60 |
| 学習 2018〜2023 | ベルリン | 660.78 | 256.65 | 372.89 | 857.76 |
| 検証 2024 | 東京 | 712.06 | 201.94 | 371.76 | 818.21 |
| 検証 2024 | ベルリン | 668.29 | 291.05 | 349.52 | 889.04 |

- 全体の MAE では、概算式は「いつも上限」より大きく悪い（概算式は、正解が上限の行のほとんどで上限より下を答える）。上限より下の行だけなら、概算式のほうが良い。

### 分割と評価

- 時系列分割：**学習 2018〜2023（6 年）、検証 2024、テスト 2025**（年は UTC。2026-10-13 に #9 で確定）。ランダム分割はしない。
  - 観測のしかたが途中で変わっている：ベルリンは 2022 年の途中から自動観測（電文の `AUTO`）になり、2023 年からはすべて自動観測。東京は 2023 年から `CAVOK` の割合が約 2 倍。検証・テストの年は、どちらも変化の後。
  - 上限で打ち切った目的変数で見ると、年による天気の違いのほうが変化の前後の差より大きいので、学習は年を多く取る（6 年）。5 年（2019〜2023）は、変化の前の年が 1 つ減るだけなので採らない。
  - **#11 で 1 回だけ、学習を 2021〜2023（3 年）にした場合と、検証の年（2024）の MAE で比べる**。3 年のほうが良ければ替える。テストの年はこの比較に使わない。結果は `docs/model-card.md` に書く。
- 指標：MAE（m）。都市別・季節別にも算出する。
  - 季節は現地の月で分ける：冬 12〜2 月、春 3〜5 月、夏 6〜8 月、秋 9〜11 月（2026-10-13 決定、#9）。
- 評価関数は `ml/evaluate.py`（2026-10-13、#10）。正解（`target_m`）のない行は数えない。出すもの：
  - 行数と全体の MAE。
  - 上限より下の行（`target_m < 1524`）だけの行数と MAE。
  - 「上限より下にあるか」の当たり外れ：正解と予測の組み合わせの 4 つの件数と、正解率。予測がちょうど上限・上限より上は「上限より下ではない」。適合率・再現率・F1 は出さない（件数から計算できる）。
  - 全体・都市別・都市 × 季節別。`reports/` に書く値は小数 2 桁に丸める。
- **成功基準（2026-10-13 決定、#10）**：テストの年（2025）で、都市ごとに、次の 2 つを両方満たす。
  1. 全体の MAE が、「いつも上限（1,524 m）と答える」より 10% 以上小さい。
  2. 上限より下の行だけの MAE が、ベースライン（概算式）より 10% 以上小さい。
  - 理由：全体の MAE だけを概算式と比べると、いつも上限と答えるだけで 60% 以上の改善になる（上の「ベースライン」の表）。1 は「雲が低いかどうか」、2 は「低いときの高さ」を見る。片方だけなら、上限に寄せるか概算式をまねるかで満たせる。
  - 10% という数値には、データ上の根拠はない（学習するまで、どこまで下がるか分からない）。

### リーク・ずれ対策

- 予測時点より後の情報を特徴量に使わない。
- 学習は過去データ、推論は予報データを使うため、その差の影響を `docs/model-card.md` に記録する。
- 特徴量作成は `ml/features.py` のみに実装し、学習と推論で共有する。
  - #10 の時点で入っているのは、#9 の `ml/eda.py` から移した 3 つ（現地の時、季節、気温と露点の差）。ほかの特徴量は #11。

### ノートブック

| ファイル | 内容 | 成果物 |
|---|---|---|
| `01_data_fetch.ipynb` | METAR・Open-Meteo の取得と時刻結合 | `data/processed/observations.parquet`（生データは `data/raw/`） |
| `02_eda.ipynb` | 欠損、分布、季節差、都市差、露点差との関係。出力を残してコミットする（全期間で実行したもの。`DATA_FETCH_MODE` の既定 `sample` では fixture の 2 日ぶんで動く） | `docs/eda.md`（要約） |
| `03_baseline.ipynb` | ベースライン評価、評価関数の確定 | `reports/baseline.json` |
| `04_train.ipynb` | 学習 | `models/cloud_base.joblib` |
| `05_evaluate.ipynb` | テスト評価、都市別・季節別 | `reports/metrics.json`、`docs/model-card.md` |

### データ取得（#8 で決めたこと、2026-10-12）

- 期間は 2018-01-01〜2025-12-31（UTC）。都市 × 年ごとに取得する（2 都市 × 8 年 × 2 つのAPI ＝ 32 回）。
- 生データ（応答のまま）を `data/raw/<提供元>/<city>_<年>.<csv|json>` に保存し、あれば使う（再実行で外部APIを呼ばない）。取り直すときは人間がファイルを消す。
- 成果物は `data/processed/observations.parquet` の 1 ファイル。1 行 ＝ 都市 × 正時（UTC）。行の順は 都市 → 時刻。
- 結合：正時ごとに、前後 30 分以内（ちょうどを含む）で最も近い METAR を 1 つ付ける。同じ距離が前後にあるときは早いほう。METAR のない正時も行を残し、METAR の列を欠損にする。
- `ceiling_m` は、最も低い BKN または OVC の層の高さ（m）。該当する層がなければ欠損（「なし」の扱いは #9 で決める）。量が BKN・OVC でも高さが欠損の層は飛ばして、次の層を見る。
- 単位は摂氏・メートル（IEM の華氏・マイル・フィートを直す）。気圧は Open-Meteo の値を使う（METAR の海面気圧は対象の 2 空港では入っていない）。
- ノートブックは環境変数 `DATA_FETCH_MODE` で切り替える。既定の `sample` は `tests/fixtures/data_raw/` の 2 日ぶんを読み、外部と通信せず、一時的な場所に書く。全期間の取得は `full` を明示したときだけ。
- 取得できる年は 1940〜2100 年に限る（それ以外は通信せずにエラー。下限は過去データの開始年、上限は `/daylight` の日付の範囲に合わせた。2026-10-12 のレビューで決定）。
- 高さのない BKN・OVC の層（電文の `BKN///`）が東京に多い。BKN・OVC があるのに `ceiling_m` が欠損の正時が 11,397、高さのない層を飛ばして別の層から `ceiling_m` が決まった正時が 1,653 ある。**#9 で「飛ばして次の層を見る」のままと決めた**（飛ばした層はすべて、値を決めた層より上にあり、値は変わらない。上の「#9（EDA）で決めたこと」）。
- 依存：pandas・pyarrow・matplotlib（#9 で追加。EDA の図）は依存グループ `ml` に入れる（`uv sync` で入る）。API のイメージ（`Dockerfile`）には入れない。pandas を読み込めない PC では、`Dockerfile.dev` のイメージの中でテストを実行する。

| 列 | 内容 |
|---|---|
| `city` | `tokyo`／`berlin` |
| `time` | 正時（UTC） |
| `temperature_c`、`dew_point_c`、`relative_humidity`、`pressure_msl_hpa`、`precipitation_mm`、`weather_code`、`cloud_cover`、`cloud_cover_low`・`_mid`・`_high`、`wind_speed_ms` | Open-Meteo の過去データ（その時刻の値。`precipitation_mm` だけ前の 1 時間の合計） |
| `metar_observed_at` | 付けた METAR の観測時刻（UTC）。なければ欠損 |
| `metar_temperature_c`、`metar_dew_point_c`、`visibility_m` | METAR の気温・露点・視程 |
| `sky_cover_1〜4`、`sky_height_1_m〜4_m` | 雲の層の量（FEW・SCT・BKN・OVC など）と高さ（m） |
| `weather_codes`、`metar` | 天気の記号、もとの電文 |
| `ceiling_m` | 目的変数のもと。最も低い BKN・OVC の高さ（m） |

## 10. 非機能要件

- キャッシュヒット時のレスポンス：手元で p95 100ms 以下を目安
- テストカバレッジ：`app/` と `ml/` で 80% 以上
- ログ：構造化ログ（JSON）。シークレット・Webhook URL を出さない。
- 再現性：`data/` は git に入れず、`01_data_fetch` で再取得できる。依存は `uv.lock` で固定。

## 11. セキュリティ要件

- シークレットは環境変数と GitHub Secrets のみ。`.env` は `.gitignore`、`.env.example` を用意。
- 入力検証：city は許可リスト（Enum）、その他パラメータは型と範囲を検証。
- SSRF 対策：ユーザー入力から URL を組み立てない。
- Docker：slim ベースイメージ、非 root ユーザーで実行、不要なファイルは `.dockerignore`。
- 依存：`pip-audit` を CI で実行、Dependabot を有効化。
- GitHub Actions：`permissions` は最小限（既定は `contents: read`）、外部 Action はバージョンを固定。
- シークレット混入対策：GitHub の secret scanning を有効化。
- Claude Code：`.claude/settings.json` で `.env` の読み取りを拒否。破壊的操作は行わせない。

## 12. テスト方針（TDD）

- 各機能は Red → Green → Refactor で進め、Red の段階でテストが失敗することを確認する。
- 外部API：`respx` でモックし、`tests/fixtures/` の保存済み実レスポンスを使う（契約テスト）。
- 境界値：不正な city、外部APIのタイムアウト、5xx、欠損値、キャッシュ期限切れ、stale の上限、未知の天気コード。
- 太陽計算：夏至・冬至・春分、天文薄明が終わらない日（ベルリンの夏至前後）、夏時間の切り替え日、日付範囲の端。
  期待値は外部の信頼できる計算結果を `tests/fixtures/` に保存して使う（AIが期待値を作らない）。
- ML：`ml/features.py` の単体テスト、評価関数のテスト、ノートブックは nbmake で小さなサンプルデータを使って実行確認。
- テストを弱めて通すことは禁止（CLAUDE.md 参照）。

## 13. CI/CD

| ワークフロー | きっかけ | 内容 |
|---|---|---|
| `ci.yml` | PR | ruff、mypy、pytest（カバレッジ 80% 未満で失敗）、pip-audit、nbmake（サンプルデータ。外部と通信しない。#8 で追加）、docker build |
| `cd.yml` | main へのマージ・タグ | イメージをビルド → コンテナ起動してスモークテスト → ghcr.io へ push |
| `notify.yml` | schedule（毎朝） | コンテナを実行して Discord に通知 |

## 14. 機能一覧とマイルストーン

| # | 機能 | 受け入れ条件 | 状態 |
|---|---|---|---|
| 1 | 雛形 | `/health` が 200、pytest・ruff・mypy が通る、Dockerfile でビルドできる | 完了 |
| 2 | CI | PR で ci.yml が実行され、失敗時に PR がマージできない | 進行中（ci.yml 導入済み。PR での実行確認とブランチ保護の設定が残っている） |
| 3 | 天気取得（現在） | `/weather` の `current` が仕様どおり。天気コードの分類（未知コードは `unknown`）。外部APIはモックでテスト | 完了 |
| 4 | 天気予報（時間・日） | `hourly` 24件・`daily` 7日分が仕様どおり。日付は現地の日付で区切られる | 完了 |
| 5 | キャッシュ | TTL 内は外部APIを呼ばない。メモリ → Redis に切り替え可能 | 完了 |
| 6 | エラー処理 | タイムアウト・5xx でリトライ、stale 返却、502 の各テストが通る | 完了 |
| 7 | 日照・暗い時間 | `/daylight` が仕様どおり。Open-Meteo の日の出入りと ±2 分以内。境界のケースのテストが通る | 完了 |
| 8 | データ取得 | `01_data_fetch` で両都市のデータを取得・結合できる | 完了 |
| 9 | EDA | `02_eda` 完了、シーリングなしの扱いを決定し `docs/eda.md` に記録 | 完了 |
| 10 | ベースライン | `03_baseline` で都市別 MAE を算出、評価関数をテスト付きで `ml/` に実装 | 完了 |
| 11 | 学習・評価 | `04`・`05` 完了、ベースラインとの比較を `docs/model-card.md` に記録 | 未着手 |
| 12 | 推論API | `/cloud-base` が仕様どおりに返る。モデルなしで 503 | 未着手 |
| 13 | Discord通知 | 毎朝通知が届く（天気・日照・雲底）。Webhook URL がログに出ない | 未着手 |
| 14 | CD | main マージでスモークテスト後に ghcr.io へ push される | 未着手 |
| 15 | UI（任意） | 現在の天気・予報・日照・雲底を表示する簡単な画面 | 未着手 |

## 15. AI駆動開発の記録

日々の記録は `docs/dev-log.md` に置く。ある程度溜まったら、観点別（プロンプト・コンテキスト・コスト・誤り対策・品質評価・安全性・TDD）のまとめを別途作る。
