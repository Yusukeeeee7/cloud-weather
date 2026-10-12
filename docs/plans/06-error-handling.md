# 計画：#6 エラー処理（Issue #11）

状態：承認済み

## 目的と受け入れ条件

spec.md「14. 機能一覧」より：

> | 6 | エラー処理 | タイムアウト・5xx でリトライ、stale 返却、502 の各テストが通る |

spec.md「6. キャッシュ」より：

> - 外部API失敗時は、最大6時間前までのキャッシュを `stale: true` で返す。それより古ければ 502。

spec.md「7. 外部API・データ」より：

> - 外部通信のタイムアウト：接続 3 秒、全体 10 秒。リトライは最大 2 回（指数バックオフ）。

spec.md「5. API仕様」より：

> | 502 | `upstream_error` | 外部APIの失敗かつ使えるキャッシュがない |
>
> - 機能ごとに段階的に追加する：…#6 で `stale`（2026-10-12 決定）。未実装のキーは返さない。

関連する要件：

- spec 12：境界値のテストに「外部APIのタイムアウト、5xx、stale の上限」がある
- #5 からの申し送り：stale を返すには、保存先の期限（いまは TTL と同じ 15 分）を 6 時間に延ばす必要がある。新しいかどうかはサービス側（`_is_fresh`）で判定しているので、保存先の期限と、外部API失敗時の分岐を足す形になる

完了の確認方法：

1. `uv run pytest --cov=app --cov=ml` が通る（カバレッジ 80% 以上）
2. `uv run ruff check . && uv run ruff format --check .`、`uv run mypy app ml` が通る
3. 手動で 1 回、`docker compose up --build`（API + Redis）で次を見る（やり方は質問 9）
   - 通常どおり `/weather?city=tokyo` を呼ぶ（`cached: false`、`stale: false`）。Redis の `weather:tokyo` の残り時間が約 6 時間になっている
   - 外部APIに届かない状態にして、TTL を過ぎてから呼ぶ → 200、`stale: true`、`fetched_at` は最初の取得時刻のまま。ログにリトライの記録が出て、URL は出ない
   - 同じ状態で、キャッシュのない都市を呼ぶ → 502 `upstream_error`

## 今回やらないこと

- 外部APIが落ちている間、呼び出しそのものを止める仕組み（サーキットブレーカー、失敗の保存）。spec にない。落ちている間はリクエストごとにリトライしてから stale を返す（リスクに記録）
- バックオフへのゆらぎ（ジッター）、`Retry-After` ヘッダーの解釈（spec にない）
- 同時に来たリクエストをまとめる仕組み（#5 で入れないと決定済み）
- Redis（キャッシュ）へのリトライ。キャッシュの故障は #5 のまま（キャッシュなしとして外部APIを呼ぶ）
- `stale` を知らせる HTTP ヘッダー（`Warning` など）や、エラー表にない新しい code の追加
- `/daylight`・`/cloud-base` のエラー処理（#7・#12）。`invalid_date`・`model_unavailable` もそちらで扱う
- NaN を含む応答が検証を通る問題（#5 で別 Issue にすると決定済み）
- `daily` を「いまの日付」で選び直すこと（質問 7 の回答しだい。推奨は今回やらない）

## 変更・追加するファイル

| ファイル | 内容 |
|---|---|
| `app/clients/open_meteo.py` | `fetch_forecast` にリトライを足す。リトライするのは通信の失敗（タイムアウト・接続エラー）と 5xx。待ち時間は指数バックオフ。待つ関数は外から渡せるようにする（テストで実際に待たないため）。使い切ったら今までどおり `UpstreamError` |
| `app/services/weather.py` | 外部APIが失敗したとき（`UpstreamError`）、最初に読んだ保存値が上限（6 時間）以内なら `stale: true` で返す。なければ・古ければ・整形できなければ `UpstreamError` をそのまま上げる。保存先の期限を TTL から stale の上限に変える。`build_weather_response` に `stale` をキーワード引数で足す（既定 `False`） |
| `app/schemas.py` | `WeatherResponse` に `stale: bool` を足す |
| `app/config.py` | `open_meteo_max_retries`（既定 2、0 以上）、`open_meteo_retry_backoff_s`（既定は質問 2）、`cache_stale_max_age_s`（既定 21600、`cache_ttl_s` 以上であることを検証） |
| `app/routers/weather.py` | stale の上限をサービスに渡す |
| `tests/conftest.py` | 待ち時間を記録するだけの偽の待ち関数（テストで実際に待たない）。`client` の fixture から使えるようにする |
| `tests/app/test_open_meteo_client.py` | 下のテスト 1〜11 |
| `tests/app/test_weather_stale.py`（新規） | 下のテスト 12〜24 |
| `tests/app/test_weather_router.py`、`test_config.py` | 下のテスト 25〜31 と、既存テストの更新（下の表） |
| `docs/spec.md` | 質問の回答で決まった仕様、環境変数、機能一覧 #6 の状態。**人間の回答にある内容だけを書く** |
| `.env.example` | 追加する変数の名前だけ。**AI は書けないので人間に依頼**（ブロッカー 2） |

設計の要点：

- **リトライはクライアント（`app/clients/`）に置く**。サービスから見ると「何回か試して、だめなら `UpstreamError`」のまま。
- **リトライするもの／しないもの**（質問 3・4）：

  | 起きたこと | リトライ | 理由 |
  |---|---|---|
  | 接続・読み取りのタイムアウト、全体のタイムアウト、接続エラー | する | 受け入れ条件 |
  | 5xx | する | 受け入れ条件 |
  | 4xx（400 など） | しない | 送った内容の問題で、繰り返しても同じ |
  | 200 だが JSON でない・形が違う・項目が欠けている | しない | spec にない。すぐ stale／502 へ進む |

- **待ち時間**：`基準 × 2^(回数−1)`。基準が 0.5 秒なら 0.5 秒 → 1.0 秒（質問 2）。
- **stale の流れ**：キャッシュの読み出しは今までどおり最初の 1 回だけ。TTL 内ならそのまま返す。TTL 切れ・なしなら外部APIを呼び、失敗したら、最初に読んだ保存値を使えるか見る（読み直さない）。
  - 経過時間は「失敗が分かった時点の時刻 − `fetched_at`」で測る（リトライで時間が進むため）。
  - stale で返すときも、整形前の保存値を「いまの時刻」で整形し直す（`hourly` は選び直す。#5 と同じ）。整形できなければ 502。
  - `fetched_at` が未来の保存値は、stale としても使わない（#5 と同じ扱い）。
- **保存先の期限を 6 時間に延ばす**：「新しいか（15 分）」「stale として使えるか（6 時間）」はどちらもサービス側で `fetched_at` から判定する。保存先の期限は掃除のためだけに付ける。
- **失敗は保存しない**（#5 のまま）。stale を返しても保存値は書き換えない（`fetched_at` を新しくしない）。
- **ログ**：リトライのたびに警告（何回目か、例外の型か状態コード）。stale を返したとき警告（都市、経過秒）。URL・例外の文面・保存値は出さない。

### 既存テストへの影響（テストを弱めないための整理）

| 既存テスト | 変更 | 理由 |
|---|---|---|
| `test_weather_returns_200_and_spec_shape` ほかの `TOP_LEVEL_KEYS` | `stale` を足す | spec のとおりキーが増える |
| `"stale" not in body` を見ている 2 か所（`test_weather_returns_hourly_and_daily_shape`、`test_weather_cached_response_keeps_spec_shape`） | `body["stale"] is False` に変える | `stale` を #6 で入れるため。#5 で `cached` にしたのと同じ変更 |
| `test_service_upstream_failure_is_not_cached` の `route.call_count == 2` | タイムアウトと 500 の場合は 6（3 回 × 2）、JSON でない場合は 2 のまま | リトライで 1 回の呼び出しが最大 3 回になる。「失敗を保存せず、次もまた外部APIを呼ぶ」という確認は変えない |
| `test_weather_upstream_error_then_success`（500 → 200 の順に返すモック） | 500 を 3 回返してから 200 にする | いまのモックのままだと、1 回目のリクエストがリトライで成功してしまい、「失敗 → 回復」を確かめられなくなる |
| 失敗を起こす既存テスト（クライアント・サービス・ルーター） | 期待（`UpstreamError`／502）は変えない。待ち関数を偽物にして実際に待たないようにする | そのままだと 1 件につき 1.5 秒待つ |
| `get_weather(...)` を直接呼ぶテストの補助関数（`_call`） | 引数に stale の上限を足す | 関数の引数が増える |
| 保存先の期限が TTL と同じことを見ているテスト | 実装時に洗い出す。あれば理由を見てから直し、「実装時の変更」に書く | 保存先の期限が 6 時間になるため |

### 確認が必要な項目（記憶で確定させない）

| 項目 | 確かめ方 |
|---|---|
| `respx` で「1 回目は例外、2 回目は応答」のように順に返す書き方（`side_effect` のリストに例外と応答を混ぜられるか） | 実行して確かめる |
| `httpx` の例外の親子関係（タイムアウト・接続エラーをまとめて拾える型） | 実行して確かめる（いまは `httpx.HTTPError` で拾っている） |
| リトライの合間の待ちと `asyncio.timeout`（全体のタイムアウト）の関係 | 待ちは全体のタイムアウトの外に置く。実行して確かめる |

## テスト一覧（先に書く順）

| # | テスト名 | 種類（正常/異常/境界） | 確かめること |
|---|---|---|---|
| 1 | `test_client_retries_timeout_then_succeeds`（接続・読み取り・全体） | 異常 | **受け入れ条件**。1 回目がタイムアウト、2 回目が 200 なら結果が返る。呼び出しは 2 回 |
| 2 | `test_client_retries_5xx_then_succeeds`（500 / 502 / 503） | 異常 | **受け入れ条件**。1 回目が 5xx、2 回目が 200 なら結果が返る |
| 3 | `test_client_retries_connect_error_then_succeeds` | 異常 | 接続エラーもリトライする |
| 4 | `test_client_succeeds_on_last_attempt` | 境界 | 2 回失敗して 3 回目に成功 → 結果が返る。呼び出しは 3 回 |
| 5 | `test_client_gives_up_after_max_retries` | 境界 | 3 回とも失敗 → `UpstreamError`。呼び出しはちょうど 3 回（4 回目はない） |
| 6 | `test_client_backoff_is_exponential` | 正常 | 待ち関数に渡された秒が 基準、基準 × 2 の順。最後の失敗の後は待たない。成功したときは待たない |
| 7 | `test_client_does_not_retry_4xx`（400 / 404 / 429 ※質問 3） | 異常 | 1 回だけ呼んで `UpstreamError`。待たない |
| 8 | `test_client_does_not_retry_invalid_body` | 異常 | 200 で JSON でない応答は 1 回だけ呼んで `UpstreamError` |
| 9 | `test_client_first_success_does_not_wait` | 正常 | 最初から成功なら呼び出し 1 回、待ちなし（既存の正常系が変わらないこと） |
| 10 | `test_client_respects_configured_retries` | 境界 | `OPEN_METEO_MAX_RETRIES=0` なら 1 回だけ。設定の値が届いていること（直書きでないこと） |
| 11 | `test_client_retry_logs_do_not_leak` | 異常 | リトライの警告ログが出て、URL・ホスト名・例外の文面を含まない |
| 12 | `test_service_upstream_failure_returns_stale` | 異常 | **受け入れ条件**。TTL 切れの保存値があり外部APIが失敗 → `stale: true`、`fetched_at` は最初の取得時刻 |
| 13 | `test_service_stale_max_age_boundary` | 境界 | spec 12「stale の上限」。上限の 1 秒前は返す・ちょうど（質問 5）・1 秒後は `UpstreamError` |
| 14 | `test_service_failure_without_cache_raises` | 異常 | **受け入れ条件**。保存値がなく外部APIが失敗 → `UpstreamError` |
| 15 | `test_service_fresh_hit_is_not_stale` | 正常 | TTL 内は `cached: true`・`stale: false`。外部APIを呼ばない |
| 16 | `test_service_fresh_fetch_is_not_stale` | 正常 | 外部APIから取得したとき `cached: false`・`stale: false` |
| 17 | `test_service_stale_reselects_hourly_by_now` | 境界 | stale で返すとき、`hourly` の先頭がいまより後の最初の正時。期待値は fixture の該当する行から読む |
| 18 | `test_service_stale_does_not_overwrite_entry` | 正常 | stale を返した後も保存値は元のまま。外部APIが直れば次は取得し直して `stale: false`、`fetched_at` が新しくなる |
| 19 | `test_service_invalid_response_returns_stale`（`current` 欠損 / JSON でない） | 異常 | 壊れた応答のときも stale を返す（質問 4） |
| 20 | `test_service_unusable_stale_entry_raises`（壊れた保存値 / いまの時刻で整形できない / `fetched_at` が未来） | 異常 | stale として使えない保存値のときは `UpstreamError`。500 にしない |
| 21 | `test_service_stores_with_stale_max_age` | 正常 | 保存先に渡す期限が stale の上限（TTL ではない） |
| 22 | `test_service_respects_configured_stale_max_age` | 境界 | 上限を 60 秒にして、60 秒前後で結果が変わる（設定の値が届いていること） |
| 23 | `test_service_cache_read_failure_and_upstream_failure_raises` | 異常 | キャッシュも外部APIも失敗 → `UpstreamError` |
| 24 | `test_service_stale_is_logged` | 異常 | stale を返したとき警告ログが出て、URL・保存値を含まない |
| 25 | `test_weather_returns_stale_when_upstream_fails`（memory / redis） | 異常 | `GET /weather`：1 回目 200、TTL 後に外部APIが失敗 → 200、`stale: true`、キーの集合は spec と同じ |
| 26 | `test_weather_stale_older_than_limit_returns_502` | 境界 | 6 時間を過ぎた保存値しかないとき 502 `upstream_error` |
| 27 | `test_weather_retries_then_returns_200` | 異常 | 外部APIが 1 回失敗して 2 回目に成功 → 200、`stale: false`、`cached: false` |
| 28 | `test_weather_shape_includes_stale` | 正常 | 通常の応答に `stale: false` がある。最上位のキーの集合が spec と一致 |
| 29 | `test_weather_recovers_after_stale` | 正常 | stale を返した後、外部APIが直れば `stale: false` に戻る |
| 30 | `test_settings_retry_and_stale_defaults_and_validation` | 異常/境界 | 既定値（2 回、21600 秒など）。リトライ回数が負、基準が 0 以下、stale の上限が TTL 未満のとき検証エラー |
| 31 | `test_openapi_includes_stale` | 正常 | `/openapi.json` の `WeatherResponse` に `stale` がある |

- すべて `respx` でモックし、テストから外部APIを呼ばない。fixture は #4 のものをそのまま使う（取り直さない）。
- 時刻は `FakeClock`、待ちは偽の待ち関数で進める。テストで実際に待たない。
- 期待値は「時計をずらした量」と fixture の行から読む。AI が計算して作る値はない。
- Red の確認：クライアント（1〜11）→ サービス（12〜24）→ ルーター・設定（25〜31）の順に、テストを先に書いて失敗を実行で確かめる。実装前から通るテスト（15・16 など「変わらないこと」の確認）は、実装後にわざと壊して失敗することを確かめる（#5 と同じやり方）。

## 追加する依存パッケージ

なし（リトライは自分で書く。20 行ほどの見込み）。

| 検討したもの | 使わない理由 |
|---|---|
| `tenacity` | 依存が 1 つ増える。今回の条件（最大 2 回、2 種類の失敗）なら自作で足りる |
| `httpx` のトランスポートの `retries` | 接続の失敗だけが対象で、5xx・読み取りタイムアウトはリトライされない（ライブラリの説明による。使わないので実行での確認はしない） |

## セキュリティ上の注意

- 入力検証：変更なし（`city` は Enum）。追加する設定値は範囲を検証する（リトライ回数は 0 以上で上限つき、待ち時間は 0 より大きい、stale の上限は TTL 以上）。
- シークレット：新しいシークレットはない。`.env` は読まない。`.env.example` は人間が追記する。
- 外部通信（ホスト・タイムアウト）：
  - 通信先は `api.open-meteo.com` のまま。リトライも同じ URL・同じパラメータで、利用者の入力から URL を作らない。
  - タイムアウトは接続 3 秒・全体 10 秒のまま（リトライとの関係は質問 1）。
  - **リトライで外部APIの呼び出しが最大 3 倍になる**。落ちている相手に負荷をかけすぎないよう、回数に上限を付け、4xx はリトライしない。Open-Meteo の上限（600 回/分）に対しては、キャッシュがあるので通常は問題にならない。
- 古い値を返すことの安全性：stale の応答は `stale: true` と元の `fetched_at` で古いことが分かる。保存値は #5 と同じ厳しい検証を通してから返す。
- エラー・ログ：502 の文面は今までどおり固定。リトライ・stale のログに URL・例外の文面・保存値を出さない。

## 実行のたびに枠を使うものの見積もり

- 外部API（Open-Meteo）：手動確認で **2〜4 回**（保存値を作るための通常の呼び出し）。失敗させる確認は外部APIに届かない設定で行うので、枠を使わない。テストからは 0 回。
- GitHub Actions：PR の作成で 1 回、レビュー後の修正と dev-log をまとめて 1 回の **計 2 回** を目安。

## リスク・未決事項

- **待ち時間が長くなる**：タイムアウトで 3 回とも失敗すると、最悪 10 秒 × 3 ＋ 待ち 1.5 秒 ＝ 約 31.5 秒かかってから stale／502 が返る（質問 1 の案 A の場合）。5xx や接続拒否のようにすぐ返る失敗なら約 1.5 秒。
- **落ちている間は毎回リトライする**：失敗を覚えておく仕組みがないので、外部APIが落ちている間は、TTL 切れのリクエストごとに最大 3 回呼んでから stale を返す。「今回やらないこと」に記録。
- **stale で返す `daily` は取得した日から始まる**：`daily` は 7 行ちょうどしか取得しておらず、いまの時刻で選び直していない。取得後に現地の日付が変わると、先頭が「昨日」になる（spec は「今日から 7 日分」）。#5 の 15 分でも起きうるが、6 時間に延びると起きやすくなる（質問 7）。
- **stale で返す `current` は最大 6 時間前の値**：`current.time` と `fetched_at`、`stale` で分かる。
- **Redis の保存期間が 15 分 → 6 時間になる**：キーは 2 つだけなので量は問題にならない。
- **メモリキャッシュは再起動で消える**：再起動の直後に外部APIが落ちていると stale は返せず 502。
- **保存先の期限と上限の境目**：保存先の期限は取得の少し後から数えるので、上限ちょうどの判定はサービス側の時刻で決まる。保存先が先に消した場合は 502 になる（どちらも「6 時間を過ぎたら返さない」側に倒れる）。
- **Windows の手元環境**：`uv run uvicorn` は起動できないことがあるため、手動確認は Docker で行う。
- **Issue #11 の本文を読めていない**（`gh` がこの環境にない）。spec の機能 #6 と同じ内容という前提。

## ブロッカー（人間の対応が必要なこと）

1. **Issue #11 の本文**：spec の機能 #6 にない要件が書かれていれば教えてください。
2. **`.env.example` への追記**（実装後）：`.claude/settings.json` の拒否設定で AI は書けません。追記する変数名は、質問 8 の回答で決まったものを実装時にお渡しします。

外部API表（spec 7）で新しく使う項目はありません（呼び出しの内容は #4 のまま、回数だけが増えます）。

## 質問

### 回答（2026-10-12 人間）

- 質問 1〜9：**すべて推奨どおり**。計画を承認。
  - 1：案 A。「全体 10 秒」は 1 回の試行ごと。
  - 2：最初の 1 回 ＋ リトライ 2 回 ＝ 最大 3 回。待ち時間は 0.5 秒 → 1.0 秒（ゆらぎなし）。
  - 3：リトライするのはタイムアウト・接続エラー・5xx だけ。4xx（429 を含む）はリトライしない。
  - 4：stale を返すのは `UpstreamError` になるものすべて（壊れた応答を含む）。
  - 5：ちょうど 6 時間は返す。6 時間を過ぎたら 502。
  - 6：stale のときは `cached: true`・`stale: true`。通常の応答では常に `stale: false`。
  - 7：案 A。stale の `daily` はそのまま返す（取得した日から 7 日分。spec に注記する）。別の Issue で扱う。
  - 8：`OPEN_METEO_MAX_RETRIES`（既定 2）、`OPEN_METEO_RETRY_BACKOFF_S`（既定 0.5）、`CACHE_STALE_MAX_AGE_S`（既定 21600）。
  - 9：手動確認は `OPEN_METEO_BASE_URL=https://open-meteo.invalid` と `CACHE_TTL_S=1` で API のコンテナを起動し直す方法で行う。
- ブロッカー 1（Issue #11 の本文）：追加の要件の連絡なし。spec の機能 #6 と同じ内容として進める。

### 質問の内容

1. **「全体 10 秒」とリトライの関係**：
   - 案 A（推奨）：10 秒は **1 回の試行ごと**（いまの実装のまま）。最悪で約 31.5 秒。
   - 案 B：リトライと待ちを含めた **合計で 10 秒**。応答は早いが、1 回目が 10 秒かかるとリトライの余地がなくなる。
2. **「最大 2 回」の数え方と待ち時間**：最初の 1 回 ＋ リトライ 2 回 ＝ **最大 3 回** と読んでよいですか。待ち時間は spec に値がないので、推奨は **0.5 秒 → 1.0 秒**（基準 0.5 秒を 2 倍ずつ。ゆらぎなし）。
3. **リトライする範囲**：推奨は **タイムアウト・接続エラー・5xx だけ**。4xx はリトライしない。**429（呼びすぎ）もリトライしない** でよいですか（繰り返すと悪化するため。すぐ stale／502 に進む）。
4. **stale を返す「外部API失敗」の範囲**：推奨は **`UpstreamError` になるものすべて**（リトライを使い切った失敗、4xx、JSON でない応答、項目の欠けた応答）。別案：通信の失敗と 5xx のときだけ stale を返し、壊れた応答は 502。
5. **6 時間ちょうどの扱い**：「最大 6 時間前まで」なので、推奨は **ちょうど 6 時間は返す、6 時間を 1 秒でも過ぎたら 502**。（TTL は「15 分ちょうどから呼び直す」だったので、そろえて「6 時間未満だけ返す」にする案もあります。）
6. **stale のときの `cached`**：spec は「外部APIを呼ばずにキャッシュから返したとき `true`」で、stale は「呼んだが失敗してキャッシュから返した」場合なので、どちらとも読めます。推奨は **`cached: true`・`stale: true`**（値の出どころがキャッシュであることを表す。spec の `cached` の説明も「キャッシュの値を返したとき」に直す）。通常の応答では常に `stale: false` を返します。
7. **stale の `daily` が「昨日」から始まる場合**（リスク参照）：
   - 案 A（推奨）：**今回はそのまま返す**（`daily` は取得した日から 7 日分。spec に注記する）。別の Issue で扱う。
   - 案 B：現地の日付が変わっていたら stale として使わず 502。
   - 案 C：`forecast_days` を 8 にして選び直す（外部APIの呼び方と fixture の取り直しが要るので、#6 の範囲を超える）。
8. **環境変数の名前と既定値**：`OPEN_METEO_MAX_RETRIES`（既定 2）、`OPEN_METEO_RETRY_BACKOFF_S`（既定 0.5）、`CACHE_STALE_MAX_AGE_S`（既定 21600）でよいですか。
9. **手動確認で外部APIを失敗させる方法**：推奨は、API のコンテナだけを `OPEN_METEO_BASE_URL=https://open-meteo.invalid`（存在しないことが決まっている名前。どこにも届かない）と `CACHE_TTL_S=1` で起動し直し、Redis に残っている保存値で `stale: true` を見る方法です。spec の「通信先は表のホストのみ」に対して、確認のための一時的な設定として問題ないですか。

## 実装時の変更

- **Red の確かめ方**：#5 と同じく、テストが収集エラーではなく個々の理由で失敗するように、実装の前に「何もしない骨組み」を置いた（設定の 3 項目を検証なしで、待つ関数 `wait` を呼ばれない状態で、`get_weather` の引数 `stale_max_age_s` を使われない状態で）。その状態で 62 件が失敗・371 件が通過。
  - 骨組みでも通った新しいテスト 22 件（「しないこと」を確かめる種類）は、実装後に **実装をわざと壊して失敗することを確かめた**（10 通り。1 つずつ壊して全テストを実行し、確認後に元へ戻して 433 件が通ることを確認）：
    1. 4xx もリトライする → `test_client_does_not_retry_4xx` ほかが失敗
    2. JSON でない応答もリトライする → `test_client_does_not_retry_invalid_body` ほかが失敗
    3. stale の上限を見ない → `test_service_stale_max_age_boundary`、`test_weather_stale_older_than_limit_returns_502` ほかが失敗
    4. 取得時刻が未来の保存値も stale として使う → `test_service_entry_from_future_is_not_returned_as_stale` が失敗
    5. 保存値をいまの時刻で選び直さない → `test_service_entry_invalid_at_now_is_not_returned_as_stale`、`test_service_stale_reselects_hourly_by_now` ほかが失敗
    6. リトライ回数を 2 に直書き → `test_client_respects_configured_retries`、`test_client_backoff_is_exponential` が失敗
    7. 待ち時間の基準を 0.5 に直書き → `test_client_backoff_is_exponential` が失敗
    8. TTL 内でも `stale: true` にする → `test_service_fresh_hit_is_not_stale` ほかが失敗
    9. stale のとき `cached: false` にする → `test_service_upstream_failure_returns_stale` ほかが失敗
    10. 外部APIの失敗を拾わない（stale を返さない） → stale 関連の 17 件が失敗
  - **壊して確かめていないもの**：`test_client_first_success_does_not_wait`（成功したのに待つ実装は自然な壊し方がない）、`test_service_corrupted_entry_is_not_returned_as_stale`（壊れた保存値を捨てる処理は #5 のもので、#5 のテストでも確かめている）、設定の型の検証（`abc`・`1.5` を数値として受け付けない。pydantic の型による）。
- **待ちの差し替え方を計画から変えた**：計画は「待つ関数を外から渡せるようにする」だったが、`app/clients/open_meteo.py` の関数 `wait` を、`tests/conftest.py` の自動適用の fixture（`waits`）で差し替える形にした。アプリが起動時に作るクライアントにも効くので、ルーターのテストも実際に待たない。テストは `waits`（待った秒の一覧）で待ち時間を確かめる。
- **リトライの実装**：`UpstreamError` の子の `_RetryableError`（クライアントの中だけで使う）を、通信の失敗と 5xx のときに上げる。外から見える例外は今までどおり `UpstreamError`。依存の追加はなし。
- **リトライ回数の上限**：`OPEN_METEO_MAX_RETRIES` は 0〜5（計画の「上限つき」の値を 5 にした。spec には書いていない）。
- **計画から増減したテスト**：
  - 計画の 28（`stale: false` を含む形）は、既存の 2 件（`"stale" not in body` → `body["stale"] is False`）と `TOP_LEVEL_KEYS` の更新で兼ねた。
  - 計画の 20 は 3 件に分けた（壊れた保存値／未来の保存値／いまの時刻で整形できない保存値）。
  - 足したもの：都市ごとに stale を返すこと、キャッシュなしで 3 回呼んでから 502 になること、stale の上限の設定がルーターまで届くこと、TTL 内は外部APIが落ちていても呼ばないこと、4xx・429 でも stale を返すこと。計 433 件（#5 の終わりは 357 件）。
- **既存テストの変更**（計画の表のとおり）：`TOP_LEVEL_KEYS` に `stale`、`"stale" not in body` の 2 か所、`test_service_upstream_failure_is_not_cached` の呼び出し回数（タイムアウトと 500 は 2 → 6、JSON でない応答は 2 のまま）、`test_weather_upstream_error_then_success` のモック（500 を 3 回返してから 200。回数は 2 → 4）、`_call` の引数、設定の既定値の確認。保存先の期限が TTL と同じことを見ている既存テストはなかった。
- **Green の後に直したテスト（1 件）**：`test_service_stale_is_logged` は単独では通り、全体で実行すると失敗した。ほかのテストがアプリを起動してログの設定（INFO）が残ると、httpx 自身の INFO ログ（リクエストの URL を含む）が、最初の取得のぶんだけ記録に入るため。確認の対象を「アプリのログ（`app.` で始まるロガー）」に絞った。実装は変えていない。
  - 関連して分かったこと：INFO のログには、httpx が出すリクエストの URL（緯度・経度などのパラメータ。秘密の値はない）が入る。#3 からの動きで、今回は変えていない。
- **手動確認**（2026-10-12T19:58Z ごろ、Docker。API + Redis）：
  - 通常：`/weather?city=tokyo` が 200、`cached: false`・`stale: false`、0.29 秒。Redis の `weather:tokyo` の残り時間は 21599 秒（約 6 時間）。
  - API のコンテナだけを `OPEN_METEO_BASE_URL=https://open-meteo.invalid`・`CACHE_TTL_S=1` で起動し直した後：`tokyo` は 200、`cached: true`・`stale: true`、`fetched_at` は最初の取得時刻のまま、1.65 秒（待ち 0.5 秒 + 1.0 秒）。`berlin`（保存値なし）は 502 `upstream_error`、1.53 秒。
  - ログ：1 リクエストにつき「request failed: ConnectError」3 行、「retry 1 of 2」「retry 2 of 2」、stale のときは「returning stale cache (tokyo, 9 s old)」。URL は出ていない。
  - stale を返した後も Redis の残り時間は減り続けていた（21589 秒。保存し直していない）。
  - 確認していないこと：タイムアウトで 3 回とも失敗する場合の実際の待ち時間（約 31.5 秒の見込み）、6 時間を過ぎた保存値での 502（自動テストでは確認済み）。
- **外部APIの呼び出し回数**：手動確認の 1 回（見積もりは 2〜4 回）。fixture は取り直していない。
- **`.env.example` を更新できていない**（#5 と同じ理由）。**人間の対応が必要**。追記する変数名：`OPEN_METEO_MAX_RETRIES`、`OPEN_METEO_RETRY_BACKOFF_S`、`CACHE_STALE_MAX_AGE_S`。
- **残っているリスク**：計画の「リスク・未決事項」のとおり（最悪で約 31.5 秒待つ、落ちている間は毎回リトライする、stale の `daily` が「昨日」から始まりうる）。
- **後の機能への申し送り**：
  - stale の `daily` を「今日から」にする件は別の Issue（spec 5 に注記済み）。
  - #13 Discord 通知：通知の文面で `stale` をどう扱うか（古い値であることを書くか）を計画で決める。
- **レビュー後の変更**（2026-10-12、人間の回答「推奨でお願いします」）：
  - **リトライの対象を狭めた**：`httpx.HTTPError` をまとめてリトライしていたため、決めた範囲（タイムアウト・接続エラー・5xx）より広く、`DecodingError`（圧縮の壊れた応答）と `TooManyRedirects` もリトライしていた（例外の親子関係を実行して確かめた）。リトライするのは `httpx.TransportError` と全体のタイムアウトだけにし、それ以外の `httpx.HTTPError` は 1 回で `UpstreamError` にした。
    - 先にテストを足して失敗を確かめた（`test_client_does_not_retry_non_transport_errors` の 2 件が「呼び出し 3 回」で失敗）。その後に実装を直した。
    - 途中で切れた接続（`ReadError`・`RemoteProtocolError`）は通信の失敗としてリトライする（`test_client_retries_dropped_connection_then_succeeds`。直す前から通っていた）。
  - **spec に決定として書いた**：`CACHE_STALE_MAX_AGE_S` は `CACHE_TTL_S` 以上、`OPEN_METEO_MAX_RETRIES` の範囲は 0〜5。どちらも最初は質問への回答ではなく AI が決めていたもので、レビューで指摘し、そのまま認める回答をもらった。
  - **`test_service_stale_is_logged`** は、確認の対象をアプリのログに絞ったままにする。httpx のログに URL が出る件は別の Issue にする。
  - **`test_service_stale_age_is_measured_after_the_failure` を足した**：呼ぶたびに進む時計で、リトライの間に 6 時間をまたぐ場合に stale を返さないこと。実装が先にあるテストなので、経過時間を「外部APIを呼ぶ前の時刻」で測るように壊して、この 1 件だけが失敗することを確かめた（確認後に元へ戻した）。
  - **`test_client_retries_total_timeout_then_succeeds`** のタイムアウトを 0.2 秒から 1 秒に広げた（遅い環境で 2 回目の応答が間に合わずに失敗するのを避ける）。
  - 計 438 件、カバレッジ 98.93%。
  - `.env.example` は人間が追記済み（AI は中身を読めないので、内容は確認していない）。
