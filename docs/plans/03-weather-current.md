# 計画：#3 天気取得（現在）（Issue #5）

状態：承認済み

## 目的と受け入れ条件

spec.md「14. 機能一覧」より：

> | 3 | 天気取得（現在） | `/weather` の `current` が仕様どおり。天気コードの分類（未知コードは `unknown`）。外部APIはモックでテスト |

spec.md「5. API仕様」`GET /weather?city=tokyo` より（今回の対象は `current` と、それを包む外側の項目）：

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
  "source": "open-meteo",
  "fetched_at": "2026-10-12T02:55:00Z"
}
```

関連する要件：

- spec 3：`city` は許可リスト（`tokyo` / `berlin`）のみ。緯度・経度・タイムゾーンは spec の表の値を使う
- spec 5 共通：時刻は ISO 8601（UTC、末尾 `Z`）。エラー形式は `{"error": {"code": ..., "message": ...}}`、許可リスト外は 422 `invalid_city`
- spec 5：未知の天気コードはエラーにせず `unknown` を返し、ログに残す
- spec 7：外部通信のタイムアウトは接続 3 秒・全体 10 秒。通信先は表のホストのみ
- spec 10：ログは構造化ログ（JSON）
- spec 12：外部APIは `respx` でモックし、`tests/fixtures/` の保存済み実レスポンスを使う
- #1 の計画からの持ち越し：`pydantic-settings` と構造化ログは #3 で導入する／`httpx` を本番依存へ移す／`httpx2` へ移行するか判断する

完了の確認方法：

1. `uv run pytest --cov=app --cov=ml` が通る（カバレッジ 80% 以上）
2. `uv run ruff check . && uv run ruff format --check .`、`uv run mypy app ml` が通る
3. 手動で 1 回だけ `uv run uvicorn app.main:app` を起動し、`/weather?city=tokyo` と `/weather?city=berlin` が実際の値を返すことを見る（外部API 2 回）

## 今回やらないこと

- `hourly`・`daily`（→ #4）。日ごとの項目・現地の日付での区切り・`forecast_days` もここ
- キャッシュ、`cached`・`stale` の実際の判定（→ #5）
- リトライ（最大 2 回・指数バックオフ）、stale の返却（→ #6）。**ただしタイムアウトの指定と、失敗時に 502 `upstream_error` を返すことは今回入れる**（CLAUDE.md「タイムアウトを必ず指定」。キャッシュがまだないので、外部APIの失敗は常に「使えるキャッシュがない」に当たる）
- `invalid_date`、`model_unavailable` のエラー（→ #7、#12）。エラー形式の共通部分だけ今回作る
- Redis、`docker-compose.yml`（→ #5）
- `httpx2` への移行（下の「追加する依存パッケージ」の理由で見送り）
- Open-Meteo の出典表示（CC BY 4.0 のリンク）を画面に出すこと（→ #15 UI。今回はレスポンスの `source: "open-meteo"` のみ）
- Dockerfile・CI の変更（依存は `uv.lock` 経由で入るため変更不要の見込み）

## 変更・追加するファイル

| ファイル | 内容 |
|---|---|
| `app/config.py` | `pydantic-settings` の `Settings`。Open-Meteo のベース URL、接続タイムアウト（3 秒）、全体タイムアウト（10 秒）、ログレベル。既定値は spec の値で、環境変数で上書きできる。シークレットは含まない |
| `app/logging_config.py` | 標準ライブラリの `logging` に JSON 形式のフォーマッタを付ける（依存は追加しない）。起動時に 1 回設定する |
| `app/cities.py` | `City`（Enum：`tokyo` / `berlin`）と、都市ごとの緯度・経度・タイムゾーン（spec 3 の表の値） |
| `app/errors.py` | アプリ用の例外（`UpstreamError` など）と、spec のエラー形式に変換する例外ハンドラ。FastAPI 既定の 422（`{"detail": [...]}`）を `invalid_city` の形式に置き換える |
| `app/clients/__init__.py` | 空 |
| `app/clients/open_meteo.py` | Open-Meteo Forecast を呼ぶクライアント。`httpx.AsyncClient`、タイムアウト指定、URL は設定値＋固定パス、クエリは都市の定義から組み立てる（ユーザー入力の文字列を URL に入れない）。HTTP エラー・タイムアウト・JSON でない応答を `UpstreamError` に変換する |
| `app/services/__init__.py` | 空 |
| `app/services/weather_codes.py` | 天気コード → 分類の対応表と変換関数。表にないコードは `unknown` を返し、警告ログを出す |
| `app/services/weather.py` | クライアントの生の応答を spec の形に整形する（項目名の変換、時刻を UTC の `Z` 付きに変換、`fetched_at` の付与）。応答に必要な項目がない場合は `UpstreamError` |
| `app/schemas.py` | レスポンスの pydantic モデル（`WeatherResponse`、`CurrentWeather`、`CloudCover`、`ErrorResponse`） |
| `app/routers/weather.py` | `GET /weather`。`city: City` で検証し、サービスを呼ぶ |
| `app/main.py` | weather ルーターの登録、例外ハンドラの登録、ログ設定、`AsyncClient` の生成と終了（lifespan） |
| `tests/fixtures/open_meteo/forecast_current_tokyo.json`、`..._berlin.json` | 実際の Open-Meteo の応答を保存したもの（取得方法はブロッカー 2） |
| `tests/fixtures/README.md` | 各 fixture の取得日時・取得した URL（クエリ）・加工の有無を記録する |
| `tests/conftest.py` | fixture の読み込み、`respx` のモック、時刻の固定など共通の準備 |
| `tests/app/test_weather_codes.py`、`test_open_meteo_client.py`、`test_weather_service.py`、`test_weather_router.py`、`test_config.py`、`test_logging_config.py` | 下のテスト一覧 |
| `pyproject.toml`、`uv.lock` | 依存の追加・移動（下の表） |
| `.env.example` | 追加した環境変数の名前（値なし） |
| `docs/spec.md` | 外部API表の「状態」と利用条件（人間の確認後）、天気コードの対応表を追記、機能一覧 #3 の状態、今回決まった仕様（質問の回答）を反映 |

設計の要点：

- **層の分担**：router（入力検証・HTTP）→ service（整形）→ client（外部通信）。#5 でキャッシュを service と client の間に挟める形にする。
- **外部呼び出しは 1 リクエストにつき 1 回**。#4 で同じ呼び出しに `hourly`・`daily` を足す前提で、クエリの組み立てを 1 か所にまとめる。
- **時刻**：Open-Meteo の時刻を UTC として受け取り、`2026-10-12T03:00:00Z` の形に直す。受け取り方（`timezone` を指定しない＝GMT／`timeformat=unixtime`）は下の「確認が必要な項目」。`fetched_at` はサーバーの現在時刻（UTC）。テストでは時計を差し替えて固定する。
- **`timezone` の値**は Open-Meteo の応答ではなく、spec 3 の表（自分の定義）から返す。
- **フレームワークの既定動作の確認**（#1 の反省）：FastAPI は検証エラーを既定で `{"detail": [...]}` の 422 で返す。spec のエラー形式と違うため、ハンドラで置き換える。`/openapi.json` に出る 422 の説明は既定のまま（spec は自動ドキュメントを「コードから生成」としているため手を入れない）。

**記憶で確定させないもの（実装時に実行して確かめる。ここに書いた名前は候補）**：
`httpx.Timeout` の引数と「全体 10 秒」の実現方法（httpx のタイムアウトは接続・読み取りなど段階ごとで、リクエスト全体の上限ではない可能性がある）、`respx` のモックの書き方とタイムアウトの再現方法、`pydantic-settings` の設定クラスの書き方、FastAPI の `RequestValidationError` ハンドラと lifespan の書き方。

## テスト一覧（先に書く順）

| # | テスト名 | 種類（正常/異常/境界） | 確かめること |
|---|---|---|---|
| 1 | `test_known_codes_map_to_category`（表の全コードをパラメータ化） | 正常 | 対応表の各コードが決めた分類になる（表は質問 4 の回答で確定） |
| 2 | `test_unknown_code_returns_unknown` | 境界 | 表にないコード（例：4、100、-1）が `unknown` になり、例外にならない |
| 3 | `test_unknown_code_is_logged` | 境界 | 未知コードのとき、コードの値を含む警告ログが 1 件出る |
| 4 | `test_settings_defaults_match_spec` | 正常 | 既定値が接続 3 秒・全体 10 秒、ホストが `api.open-meteo.com` |
| 5 | `test_settings_read_from_env` | 正常 | 環境変数で上書きできる |
| 6 | `test_log_output_is_json` | 正常 | ログ 1 行が JSON として読め、時刻・レベル・メッセージを含む |
| 7 | `test_client_requests_expected_host_and_params` | 正常 | 呼び出し先のホストとパス、クエリ（緯度・経度、`current` の項目、風速の単位）が計画どおり。呼び出しは 1 回 |
| 8 | `test_client_uses_city_coordinates`（tokyo / berlin） | 正常 | 都市ごとに spec 3 の緯度・経度が送られる |
| 9 | `test_client_sets_timeout` | 正常 | クライアントに設定値のタイムアウトが入っている |
| 10 | `test_client_timeout_raises_upstream_error` | 異常 | タイムアウトが `UpstreamError` になる |
| 11 | `test_client_5xx_raises_upstream_error` | 異常 | 500 / 503 が `UpstreamError` になる |
| 12 | `test_client_400_error_body_raises_upstream_error` | 異常 | Open-Meteo の 400（`{"error": true, "reason": ...}`）が `UpstreamError` になる |
| 13 | `test_client_invalid_json_raises_upstream_error` | 異常 | JSON でない応答が `UpstreamError` になる |
| 14 | `test_service_maps_fixture_to_current`（tokyo / berlin） | 正常 | fixture の値が spec の項目名に正しく移る（値は fixture から読んで比べる。AI が期待値を作らない） |
| 15 | `test_service_time_is_utc_with_z` | 正常 | `current.time` と `fetched_at` が `...Z` の形式 |
| 16 | `test_service_fetched_at_uses_clock` | 正常 | `fetched_at` が差し替えた時計の値になる |
| 17 | `test_service_missing_or_null_field_raises_upstream_error` | 境界 | fixture から項目を 1 つ消す／null にすると `UpstreamError`（API では 502 `upstream_error`） |
| 18 | `test_service_unknown_weather_code` | 境界 | fixture のコードを未知の値に差し替えると `weather` が `unknown`、`weather_code` は元の値のまま、200 |
| 19 | `test_weather_returns_200_and_spec_shape`（tokyo / berlin） | 正常 | `GET /weather?city=...` が 200。キーの集合が spec と一致（余計なキーがない）。`city`・`timezone`・`source` が正しい |
| 20 | `test_weather_invalid_city_returns_422` | 異常 | `city=osaka` で 422、ボディが `{"error": {"code": "invalid_city", "message": ...}}`。外部APIは呼ばれない |
| 21 | `test_weather_missing_city_defaults_to_tokyo` | 境界 | `city` なしの `GET /weather` が 200 で `city` が `tokyo`。外部APIには東京の緯度・経度が送られる |
| 22 | `test_weather_city_is_case_sensitive_...` / 空文字 / URL 風の文字列 | 境界 | `Tokyo`、`city=`（空文字）、`http://example.com` などが 422。外部APIは呼ばれない。空文字は「未指定」とは扱わず、既定値にしない |
| 23 | `test_weather_upstream_failure_returns_502` | 異常 | タイムアウト・5xx で 502 `upstream_error`。メッセージに外部の URL や内部の例外文を出さない |
| 24 | `test_weather_rejects_post` | 異常 | `POST /weather` は 405 |

- すべて `respx` でモックし、テストから外部APIを呼ばない。モックしていない通信が起きたらテストが失敗する設定にする。
- Red の確認：各グループでテストを先に書き、実装がない状態で失敗することを実行して確かめる。
- 既存の `tests/app/test_health.py` は変更しない。

## 追加する依存パッケージ

| パッケージ | 区分 | 理由 | 代替案 |
|---|---|---|---|
| `httpx`（0.28.1、導入済み） | dev → **本番へ移動** | 外部API呼び出し（CLAUDE.md の技術スタック）。#1 の計画で予定していた移動 | 標準ライブラリ `urllib`（タイムアウト・非同期・モックが弱い） |
| `pydantic-settings` | 本番 | 設定を環境変数から読む（CLAUDE.md の規約）。PyPI で最新 2.15.0、Python 3.14 対応を確認。間接依存に `python-dotenv`、`typing-inspection` が入る | `os.environ` を直接読む（型の検証を自分で書くことになり、規約と合わない） |
| `respx` | dev | httpx のモック（CLAUDE.md・spec 12）。PyPI で最新 0.23.1、`httpx>=0.25.0`、Python 3.14 対応を確認 | `httpx.MockTransport` を自分で使う（依存は増えないが、規約は respx を指定している） |

- **`httpx2` へは移行しない（推奨）**：PyPI で確認したところ、`httpx2` は Pydantic が引き継いだ後継（最新 2.13.1、import 名が `httpx2` に変わる）。一方 `respx` 0.23.1 の依存は `httpx` で、`httpx2` への言及がない。移行すると CLAUDE.md・spec が指定する respx でモックできなくなる見込み。そのため `httpx` 0.28.1 のまま進め、`TestClient` の非推奨の警告（`install httpx2 instead`）は残る。respx が対応したら別の Issue で移行を検討する。
- 構造化ログは標準ライブラリで書き、ログ用の依存は追加しない。

## セキュリティ上の注意

- 入力検証：`city` は Enum（許可リスト）。許可リスト外・空文字・大文字違いは 422 で、外部APIを呼ぶ前に弾く。未指定のときだけ既定値 `tokyo` を使う。他のクエリパラメータは受け取らない。
- SSRF 対策：URL は「設定のベース URL ＋ 固定パス」。クエリの緯度・経度はコード内の都市定義から取り、ユーザーが送った文字列を URL・クエリに入れない。リダイレクトは追わない（httpx の既定。実装時に確認）。
- シークレット：なし（Open-Meteo の無料利用は API キー不要。公式ページで「apikey は商用利用のみ必要」を確認）。`.env` は読まない。`.env.example` には変数名だけ書く。
- 外部通信（ホスト・タイムアウト）：`api.open-meteo.com` のみ（HTTPS）。接続 3 秒・全体 10 秒。
- エラーメッセージ・ログ：502 の応答に外部の URL・スタックトレース・例外の文面を出さない。ログにはクエリ（緯度・経度）とステータスは出してよいが、応答本文の全体は出さない。
- ベース URL を環境変数で変えられるようにすると、設定を書き換えられる人は通信先を変えられる。利用者の入力ではなく運用者の設定なので許容するが、気になる場合はコードの定数にする（質問 6）。
- 依存：追加は上の表の 2 つ（＋httpx の移動）。追加後に `uv run pip-audit` を実行する。

## 実行のたびに枠を使うものの見積もり

- 外部API（Open-Meteo、無料枠は公式ページで 600 回/分・5,000 回/時・10,000 回/日）：fixture の取得 2 回、完了時の手動確認 2 回、取り直しの予備を含めて **10 回以内**。テストからは 0 回。
- GitHub Actions：PR の作成で 1 回、レビュー後の修正と dev-log をまとめて push して 1 回の **計 2 回** を目安にする。

## リスク・未決事項

- **「全体 10 秒」の実現方法**：httpx のタイムアウトが段階ごとの場合、応答が少しずつ届くとリクエスト全体が 10 秒を超えうる。実装時に httpx の挙動を実行して確かめ、必要なら全体の上限を別の方法（例：`asyncio.timeout`）でかける。方法が変わったら「実装時の変更」に記録する。
- **Open-Meteo の値の型**：`relative_humidity_2m`・`cloud_cover` が整数で返るか小数で返るかは fixture を見て確かめる。spec の例は整数なので、小数なら丸め方を質問する。
- **`current.time` の意味**：Open-Meteo の `current` は一定間隔（`interval` 秒）に丸めた時刻を返す。spec の例（`time` が `fetched_at` より後）とも矛盾しないが、fixture で確かめる。
- **`dew_point_2m` と層別雲量が `current` で取れるか**：公式ページに「hourly の全項目は current でも使える」とあるが、`current` の一覧には載っていない。fixture の取得時に実際に返るか確かめる。返らなければ作業を止めて相談する（`hourly` の現在時刻の値で代用する案は #4 の範囲と重なる）。
- **Web ページの照合は要約ツール経由**：下の「公式ページで照合した結果」は AI がページを取得して読んだもので、要約の誤りがありうる。人間の確認（ブロッカー 1）と、fixture の実物で二重に確かめる。
- **非同期クライアントと `TestClient`**：lifespan で作った `AsyncClient` をテストで正しく開始・終了できるか、最初のテストで確かめる。
- **Issue #5 の本文を読めていない**（`gh` がなく、リポジトリは非公開）。spec の機能 #3 と同じ内容という前提。

## ブロッカー（人間の対応が必要なこと）

1. **外部API表の「未確認」項目の確認**（CLAUDE.md「未確認のものは使わない」）。今回使うのは spec 7 の表の 3 行：「予報（現在・時間）」「予報のオプション」「天気コード表」。AI が公式ページ（<https://open-meteo.com/en/docs>、<https://open-meteo.com/en/terms>、<https://open-meteo.com/en/licence>）で照合した結果は次のとおり。**人間が同じページで確かめ、合っていれば spec の状態を「確認済み」にしてください**（spec の書き換えは実装ブランチで AI が行えます）。

   | 項目 | 公式ページで照合した結果 |
   |---|---|
   | エンドポイント | `https://api.open-meteo.com/v1/forecast`（`latitude`、`longitude` を指定） |
   | 現在値の指定 | `current=` に項目名を並べる。「hourly の全項目は current でも使える」との記載あり |
   | 今回使う項目と単位 | `temperature_2m`（°C）、`apparent_temperature`（°C）、`dew_point_2m`（°C）、`relative_humidity_2m`（%）、`precipitation`（mm、直前 1 時間の合計）、`weather_code`（WMO コード）、`cloud_cover`（%）、`cloud_cover_low`（%、3 km まで）、`cloud_cover_mid`（%、3〜8 km）、`cloud_cover_high`（%、8 km から）、`wind_speed_10m`（既定は km/h） |
   | 風速の単位 | `wind_speed_unit=ms` で m/s（既定は `kmh`） |
   | タイムゾーン | `timezone` の既定は `GMT`。IANA の名前か `auto` を指定できる |
   | 時刻の形式 | 既定は `iso8601`（例：`2022-07-01T00:00`、秒とオフセットなし）。`timeformat=unixtime` で UNIX 秒 |
   | 応答の項目 | `latitude`、`longitude`、`elevation`、`generationtime_ms`、`utc_offset_seconds`、`timezone`、`timezone_abbreviation`、`current`（`time`、`interval` と各項目）。`current_units` はページ上で確認できなかった |
   | エラー | 不正なパラメータは HTTP 400、`{"error": true, "reason": "..."}` |
   | 天気コード | 0, 1, 2, 3, 45, 48, 51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 71, 73, 75, 77, 80, 81, 82, 85, 86, 95, 96, 99（意味は質問 4 の表）。要約には 97 も出たが、誤りの可能性があるため要確認 |
   | 利用条件 | 無料の API は非商用のみ。上限 600 回/分・5,000 回/時・10,000 回/日・300,000 回/月。API キー不要 |
   | ライセンス | データは CC BY 4.0。表示する場所の近くに出典のリンク（例：「Weather data by Open-Meteo.com」）が必要 |

   今回使わない項目（`precipitation_probability`、`pressure_msl`、日ごとの項目、予報日数）は #4 以降の計画で確認します。

2. **fixture（実レスポンス）の取得**：テストの期待値のもとになる実際の応答を、東京・ベルリンで 1 回ずつ取得して保存する必要があります（外部API 2 回）。ブロッカー 1 の確認が済んでクエリが確定した後、実装の最初に AI が `curl` で取得してよいか、人間が取得して置くかを決めてください（質問 5）。

3. **Issue #5 の本文**：spec の機能 #3 にない要件が書かれていれば教えてください。

## 質問

### 回答（2026-10-12 人間）

- 質問 2：**`city` を付けずに呼んだ場合は `tokyo` を既定値にする**（422 にしない）。spec にない仕様なので、実装ブランチで spec.md「5. API仕様」の `/weather` に追記する。`/daylight`・`/cloud-base` の既定値は今回決めない（それぞれの機能の計画で確認する）。
- 質問 1・3・4・6・7・8：推奨どおり。
  - 1：#3 では `city`・`timezone`・`current`・`source`・`fetched_at` だけを返す。
  - 3：`current` の項目が欠けている・null なら 502 `upstream_error`。
  - 4：分類表は案のとおり（1 → `clear`、56・57 → `drizzle`、66・67 → `rain`）。
  - 6：タイムアウト 2 つ・ログレベル・ベース URL を環境変数で上書き可能にする。
  - 7：`pydantic-settings`（本番）・`respx`（dev）の追加と `httpx` の本番への移動を承認。`httpx2` へは移行しない。
  - 8：JSON ログは今回入れる。
- 質問 5（fixture の取得）：**AI が `curl` で 2 回（東京・ベルリン各 1 回）取得してよい**。
- ブロッカー 1（外部API表の確認）：**人間が公式ページで確認済み**。実装ブランチで spec.md の外部API表の 3 行（予報の現在値・オプション・天気コード表）を「確認済み」にし、利用条件を書き込む。
  - 天気コード 97 について個別の回答はない。分類表（質問 4）に 97 は入れておらず、返ってきた場合は `unknown` になる。
- ブロッカー 2（fixture の取得）：上の回答で解決。ブロッカー 3（Issue #5 の本文）：追加の要件の連絡なし。spec の機能 #3 と同じ内容として進める。

### 質問の内容

1. **#3 の時点のレスポンスの形**：spec の例には `hourly`・`daily`・`cached`・`stale` があるが、これらは #4・#5・#6 の機能です。推奨は **「#3 では `city`・`timezone`・`current`・`source`・`fetched_at` だけを返し、残りのキーはそれぞれの機能で追加する」**（空の配列や固定の `false` を返すと、中身のない項目が仕様どおりに見えてしまうため）。別案：`cached: false`・`stale: false` は事実なので今回から返す。どちらにしますか。
2. **`city` を付けずに呼んだ場合**：spec は「許可リスト外の city → 422 `invalid_city`」のみ。推奨は **未指定も 422 `invalid_city`**（メッセージで「city は必須」と伝える）。よいですか。
3. **Open-Meteo の応答に項目がない・値が null の場合**：spec に記載がありません。推奨は **`current` の項目が 1 つでも欠けたら 502 `upstream_error`**（一部だけ null で返すと、利用側が全項目で null を考慮する必要が出るため）。別案：その項目だけ `null` で返す。どちらにしますか。
4. **天気コードの分類表**（spec に追記する内容）。公式の意味と、分類の案です。判断が分かれるのは ★ の行です。

   | コード | 公式の意味 | 分類（案） |
   |---|---|---|
   | 0 | Clear sky | `clear` |
   | 1 | Mainly clear | `clear` ★（`partly_cloudy` にする案もある） |
   | 2 | Partly cloudy | `partly_cloudy`（spec の例と一致） |
   | 3 | Overcast | `cloudy`（spec の例と一致） |
   | 45, 48 | Fog / Depositing rime fog | `fog` |
   | 51, 53, 55 | Drizzle（弱・中・強） | `drizzle` |
   | 56, 57 | Freezing drizzle | `drizzle` ★ |
   | 61, 63, 65 | Rain（弱・中・強） | `rain`（61 は spec の例と一致） |
   | 66, 67 | Freezing rain | `rain` ★ |
   | 71, 73, 75 | Snowfall（弱・中・強） | `snow` |
   | 77 | Snow grains | `snow` |
   | 80, 81, 82 | Rain showers | `rain` |
   | 85, 86 | Snow showers | `snow` |
   | 95, 96, 99 | Thunderstorm（96・99 は雹を伴う） | `thunderstorm` |
   | 上記以外 | — | `unknown` |

   この案でよいですか。
5. **fixture の取得は AI が行ってよいですか**（`curl` で `api.open-meteo.com` を 2 回。取得日時とクエリを `tests/fixtures/README.md` に記録し、応答は加工せず保存）。
6. **設定値にする範囲**：推奨は、タイムアウト 2 つ・ログレベル・Open-Meteo のベース URL を環境変数で上書き可能にすること。ベース URL を固定の定数にしたい場合は教えてください。
7. **依存の追加の承認**：`pydantic-settings`（本番）と `respx`（dev）の追加、`httpx` の本番への移動、`httpx2` へは移行しない方針でよいですか。
8. **構造化ログの範囲**：#1 の計画で「#3 で導入」と決めたため今回入れますが、機能を小さくしたい場合は、今回は標準のログ出力のままにして JSON 化を別の Issue に分けることもできます。推奨は今回入れる（未知コードのログが受け入れ条件に含まれるため、形式を後で変えるとテストを書き直すことになる）。

## 実装時の変更

- **fixture の取得**：2026-10-12T13:41:02Z に `curl` で東京・ベルリンを 1 回ずつ取得（どちらも HTTP 200）。加工せず保存し、取得日時と URL を `tests/fixtures/README.md` に記録した。
- **リスクに挙げていた点の結果**（実レスポンスで確認）：
  - `dew_point_2m` と `cloud_cover_low/mid/high` は `current` で返った。
  - `relative_humidity_2m` と雲量は整数で返った。丸めは入れていない（小数が返った場合は検証で 502 になる）。
  - `current.time` は `2026-10-12T13:30` の形（UTC、`interval` は 900 秒）。`utc_offset_seconds` は 0。
  - `current_units` も返った（公式ページの要約では確認できなかった項目）。風速は `m/s`。
- **時刻の受け取り方**：`timezone` も `timeformat` も指定せず、既定（GMT、ISO 8601）のまま受け取り、UTC として `Z` 付きに直す方法にした。#4 で日ごとの項目のために `timezone` を指定する場合は、この変換を見直す必要がある。
- **「全体 10 秒」の実現**：httpx のタイムアウトは段階ごと（接続・読み取り・書き込み・プール）だった（実行して確認）。`httpx.Timeout(10, connect=3)` に加えて、リクエスト全体を `asyncio.timeout(10)` で囲んだ。短い設定値で実際に打ち切られることをテストしている。
- **設定は `.env` ファイルを読まない**：`Settings` は環境変数だけを読む（`env_file` を指定していない）。`.env` を使う場合は、起動する側（docker compose など）で環境変数として渡す。docker compose を入れる #5 で必要なら見直す。
- **`.env.example` は変更しない**（2026-10-12 人間が決定）：`.env.example` には **必須の変数だけ** 名前を書く。今回追加した 4 つ（`OPEN_METEO_BASE_URL`、`OPEN_METEO_CONNECT_TIMEOUT_S`、`OPEN_METEO_TOTAL_TIMEOUT_S`、`LOG_LEVEL`）はすべて省略可能なので書かない。一覧は `app/config.py` の `Settings` にある。なお `.claude/settings.json` の `Read(./.env.*)` の拒否ルールが `.env.example` にも当たるため、AI はこのファイルを書き換えられない（必須の変数が増えたときは人間が追記する）。
- **レビュー後の変更**：
  - `LOG_LEVEL` を `DEBUG`・`INFO`・`WARNING`・`ERROR`・`CRITICAL` に限定した（小文字や誤った値で起動時に落ちていたため。設定の読み込み時に検証エラーになる）。
  - `/weather` の 422・502 を自動ドキュメントに `ErrorResponse` として載せた（既定の `{"detail": [...]}` の説明が実際の応答と違っていたため）。
  - Open-Meteo の応答の検証を厳密にした（数値の文字列や真偽値を数値として受け付けない）。小数の項目に整数が来るのは受け付ける。
  - spec.md の「`cached` は #5、`stale` は #6」という記述を、「#5・#6 の計画で決める」に直した（承認されていない割り振りを AI が推測で書いていた）。
- **計画から足したテスト**：タイムアウトの設定値の検証（0・負の数・文字列を拒否）、応答の型違い・読めない時刻・壊れた `current`、全体タイムアウトの打ち切り、リダイレクトを追わない設定、保存した実レスポンスの単位の確認、`/health` が引き続き動くこと。計 115 件（既存 4 件を含む）。
- **計画から足した小さな実装**：設定のタイムアウトに「0 より大きい」という検証を付けた（計画の「数値は範囲チェック」に当たる）。
- **422 のハンドラは検証エラーをすべて `invalid_city` にする**：今の入力は `city` だけのため。`date` が加わる #7 で、項目ごとにコードを分ける必要がある。
- **405 などの既定のエラーは FastAPI の形（`{"detail": ...}`）のまま**：spec のエラー表にないため変えていない。
- **ログ**：アプリと httpx のログは JSON で出る。uvicorn 自身のログ（起動・アクセスログ）は uvicorn の形式のまま（計画の範囲外。統一するかは別途判断）。httpx が INFO で Open-Meteo の URL（緯度・経度を含む。シークレットなし）を出す。
- **手動確認は Docker で行った**：`uv run uvicorn` は Windows のアプリケーション制御ポリシーにブロックされ起動できなかった（#1 の mypy と同じ種類の事象）。代わりに `docker build` したイメージを起動し、`/weather?city=tokyo`、`?city=berlin`、`city` なし（いずれも 200、実際の値）、`?city=osaka`（422 `invalid_city`）を確認した。
- **外部APIの呼び出し回数**：fixture 2 回＋手動確認 3 回の計 5 回（見積もりは 10 回以内）。
- **依存**：`pydantic-settings` 2.15.0 の間接依存として `python-dotenv` 1.2.4 が増えた（`typing-inspection` は導入済みだった）。追加後の `pip-audit` は「No known vulnerabilities found」。
- **`TestClient` の非推奨の警告は残っている**（`install httpx2 instead`）。計画どおり移行していない。
