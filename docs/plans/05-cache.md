# 計画：#5 キャッシュ（Issue #8）

状態：承認済み

## 目的と受け入れ条件

spec.md「14. 機能一覧」より：

> | 5 | キャッシュ | TTL 内は外部APIを呼ばない。メモリ → Redis に切り替え可能 |

spec.md「6. キャッシュ」より：

> - キー：`weather:{city}`、TTL：15分（現在・時間ごと・日ごとを 1 回の外部呼び出しでまとめて取得し、まとめてキャッシュする）
> - `/daylight` は計算のみで外部通信がないため、キャッシュしない。
> - 外部API失敗時は、最大6時間前までのキャッシュを `stale: true` で返す。それより古ければ 502。
> - 開発初期はメモリキャッシュ、その後 Redis（docker compose）に切り替える。インターフェースは共通化する。

関連する要件：

- spec 5：`cached`・`stale` をどの機能で追加するかは #5・#6 の計画で決める。未実装のキーは返さない（→ 質問 2）
- spec 10：キャッシュヒット時のレスポンスは手元で p95 100ms 以下を目安
- spec 12：境界値のテストに「キャッシュ期限切れ」がある（「stale の上限」は #6）
- #4 からの申し送り：いまは `fetched_at`（取得時刻）を「現在時刻」としても使って `hourly` の 24 件を選んでいる。キャッシュを入れると 2 つの時刻が別になるので、どちらで選ぶかを #5 で決める（→ 質問 3）

完了の確認方法：

1. `uv run pytest --cov=app --cov=ml` が通る（カバレッジ 80% 以上）
2. `uv run ruff check . && uv run ruff format --check .`、`uv run mypy app ml` が通る
3. 手動で 1 回、`docker compose up --build`（API + Redis）で起動し、`/weather?city=tokyo` を 2 回呼ぶ。2 回目が外部APIを呼ばずに返ること（`fetched_at` が 1 回目と同じ、`cached` を入れる場合は `true`）と、Redis に `weather:tokyo` があり期限が付いていることを見る
4. 同じ確認を `CACHE_BACKEND=memory` でも 1 回行う（切り替えられることの確認）

## 今回やらないこと

- 外部API失敗時に古いキャッシュを返すこと、`stale`、6 時間の上限（→ #6）
- リトライ（→ #6）
- `/daylight`・`/cloud-base` のキャッシュ（spec 6：`/daylight` はキャッシュしない。`/cloud-base` は #12 で決める）
- キャッシュを消す・無効にするためのエンドポイントやクエリ（`?refresh=1` など。spec にない）
- `Cache-Control`・`ETag` などの HTTP キャッシュのヘッダー（spec にない）
- 同時に来たリクエストを 1 回の外部呼び出しにまとめる仕組み（質問 6。推奨は今回やらない）
- CI で Redis を起動してのテスト、CD のスモークテスト（→ #14）
- Redis の永続化・認証・TLS の設定（手元の docker compose の中だけで使う。ポートは外に出さない）

## 変更・追加するファイル

| ファイル | 内容 |
|---|---|
| `app/cache/__init__.py`（新規） | 公開する名前（`Cache`、`CacheError`、`build_cache`） |
| `app/cache/base.py`（新規） | 共通のインターフェース `Cache`（`Protocol`）：`async get(key) -> str \| None`、`async set(key, value, expire_s) -> None`、`async close() -> None`。失敗を表す `CacheError` |
| `app/cache/memory.py`（新規） | `MemoryCache`。辞書に値と期限を持つ。時計は外から渡す（テストで時刻を進めるため） |
| `app/cache/redis.py`（新規） | `RedisCache`。`redis` パッケージの非同期クライアントを包む。**接続・読み書きのタイムアウトを必ず指定**。Redis 側の例外は `CacheError` に変換する |
| `app/cache/factory.py`（新規。小さければ `__init__.py` に置く） | `build_cache(settings)`：設定の値で `MemoryCache` か `RedisCache` を返す |
| `app/config.py` | `cache_backend`（`memory` / `redis`、既定 `memory`）、`cache_ttl_s`（既定 900、0 より大きい）、`redis_url`（`redis` のとき必須）、`redis_timeout_s`（質問 5）を追加 |
| `app/services/weather.py` | `get_weather` にキャッシュの読み書きを足す。`build_weather_response` に「現在時刻」と `cached` をキーワード引数で足す（既定値は今と同じ動き＝既存の呼び出しはそのまま） |
| `app/schemas.py` | `WeatherResponse` に `cached: bool` を足す（質問 2 の回答しだい） |
| `app/routers/weather.py` | キャッシュを渡す依存（`get_cache`）を足す |
| `app/main.py` | `lifespan` でキャッシュを作って `app.state` に置き、終了時に閉じる |
| `docker-compose.yml`（新規） | `api` と `redis` の 2 つ。Redis のポートはホストに公開しない。イメージの版は固定する（版は実装時に公式のイメージ一覧で確かめる。記憶で書かない） |
| `.env.example` | `CACHE_BACKEND`、`CACHE_TTL_S`、`REDIS_URL`、`REDIS_TIMEOUT_S` の名前だけ |
| `pyproject.toml`、`uv.lock` | `redis`（本番）、`fakeredis`（開発）の追加（質問 4。承認後） |
| `tests/app/test_cache_memory.py`、`test_cache_redis.py`、`test_cache_factory.py`（新規） | 下のテスト 1〜13 |
| `tests/app/test_weather_cache.py`（新規） | 下のテスト 14〜27 |
| `tests/app/test_weather_router.py`、`test_config.py` | 下のテスト 28〜31 と、既存テストの更新（下の表） |
| `docs/spec.md` | 質問の回答で決まった仕様（`cached` を入れる機能、キャッシュに関する決定）、機能一覧 #5 の状態。**人間の回答にある内容だけを書く** |

設計の要点：

- **保存するのは整形前の応答**（Open-Meteo の JSON と取得時刻）。返すたびに「いまの時刻」で `hourly` の 24 件を選び直す。整形後を保存すると、正時をまたいだときに過ぎた時刻が `hourly` の先頭に残り、spec 5 の「現在より後の最初の正時」に反する（質問 3）。
  - `fetched_at`：外部APIから取得した時刻（キャッシュから返すときも、最初に取得した時刻のまま）
  - `hourly` を選ぶ基準：リクエストを受けた時刻
- **新しいかどうかはサービス側で判定する**：`いまの時刻 − fetched_at < TTL` なら使う。時計は既にある `Clock` を使うので、テストで待たずに時刻を進められ、メモリでも Redis でも同じ判定になる。保存先の期限（Redis の `EX`、メモリの期限）は掃除のために同じ TTL を付ける（#6 では stale のために保存先の期限だけ 6 時間に延ばす想定。今回は決めない）。
- **保存する値は JSON の文字列**に統一する（`{"fetched_at": ..., "raw": {...}}`）。メモリでも同じ文字列を持つので、保存先を替えても直列化の違いで動きが変わらない。
- **保存するのは、整形に成功した応答だけ**。壊れた応答や失敗は保存しない（保存すると 15 分間 502 が続く）。
- **キャッシュから読んだ値も信用しない**：JSON として読めない、形が違う、`fetched_at` が未来、いまの時刻で整形し直すと検証に落ちる（返さない範囲にあった null が、正時をまたいで返す範囲に入った場合など）ときは、キャッシュなしとして外部APIを呼び直し、上書きする。
- **キャッシュの故障で API を止めない**（質問 7）：読み出しの失敗はキャッシュなしとして外部APIを呼ぶ。書き込みの失敗は無視して応答を返す。どちらも警告ログを残す（接続先の URL は出さない）。
- **キー**は `weather:{city}` で、`city` は Enum の値から作る（利用者が送った文字列をそのまま使わない）。許可リストが 2 都市なので、キーは最大 2 つで増えない。

### 既存テストへの影響（テストを弱めないための整理）

| 既存テスト | 変更 | 理由 |
|---|---|---|
| `build_weather_response(city, raw, FIXED_NOW)` を呼ぶ約 55 か所 | **変更なし** | 新しい引数はキーワード引数で既定値を持たせ、今までの呼び方は「いま取得した・キャッシュでない」を意味するままにする。#3・#4 のテストがそのまま通ることを回帰の確認にする |
| `test_weather_returns_200_and_spec_shape` の `TOP_LEVEL_KEYS` | `cached` を足す（質問 2 で #5 に入れると決まった場合のみ） | spec のとおりキーが増える。`stale` がないことの確認は残す |
| `tests/conftest.py` の `client` | 変更なしの見込み。`lifespan` がテストごとにメモリキャッシュを作り直すので、テスト間で値が残らない。残る場合は fixture で空にする | テスト同士が影響し合わないようにする |
| ルーターのテストで同じ都市を 2 回呼んで `call_count` を見ているもの | 実装時に洗い出す。あれば、意図（毎回呼ぶことの確認か、別の確認か）を見てから直し、変更内容を「実装時の変更」に書く | キャッシュで外部呼び出しの回数が変わるため |

### 確認が必要な項目（記憶で確定させない。ここに書いた名前は候補）

| 項目 | 候補 | 確かめ方 |
|---|---|---|
| `redis` パッケージの非同期クライアント | `redis.asyncio` の `Redis.from_url(...)`、`get`、`set(..., ex=秒)`、タイムアウトの引数（`socket_timeout`・`socket_connect_timeout`）、閉じ方（`aclose`） | 追加の承認後、実際にコードを実行して確かめる |
| `redis`・`fakeredis` の Python 3.14 対応と最新版 | 未確認 | PyPI で確かめてから承認を求める。追加後に `pip-audit` |
| `fakeredis` の非同期クライアントと、期限の確かめ方 | 時刻を進められるか、キーの残り時間（`ttl`）を読めるか | 実行して確かめる。できない場合は「期限付きで保存されたこと」を残り時間で確かめる |
| Redis の Docker イメージの版 | 未確認 | 公式のイメージ一覧で確かめて固定する |
| `docker compose` での起動順 | `depends_on` と healthcheck の書き方 | 実際に起動して確かめる |

## テスト一覧（先に書く順）

| # | テスト名 | 種類（正常/異常/境界） | 確かめること |
|---|---|---|---|
| 1 | `test_memory_get_missing_returns_none` | 正常 | ないキーは `None` |
| 2 | `test_memory_set_then_get` | 正常 | 保存した値がそのまま返る。同じキーは上書き、別のキーは別々 |
| 3 | `test_memory_expires_after_expire_s` | 境界 | 時計を進めて、期限の 1 秒前は返る・期限ちょうどと 1 秒後は `None` |
| 4 | `test_memory_rejects_non_positive_expire` | 異常 | 期限が 0 以下なら `ValueError` |
| 5 | `test_redis_get_missing_returns_none` | 正常 | `fakeredis` で、ないキーは `None` |
| 6 | `test_redis_set_then_get` | 正常 | 保存した値が文字列で返る（バイト列でない）。上書き・別キー |
| 7 | `test_redis_set_applies_expiry` | 境界 | 保存したキーに期限が付いている（残り時間が 0 より大きく `expire_s` 以下。期限なしで残らない） |
| 8 | `test_redis_errors_become_cache_error`（get / set） | 異常 | 接続できない・タイムアウトのとき `CacheError` になる（Redis の例外をそのまま外に出さない） |
| 9 | `test_redis_client_has_timeouts` | 正常 | 作ったクライアントに接続・読み書きのタイムアウトが設定されている |
| 10 | `test_build_cache_memory_by_default` | 正常 | 設定なしで `MemoryCache` |
| 11 | `test_build_cache_redis_when_configured` | 正常 | `CACHE_BACKEND=redis` と `REDIS_URL` で `RedisCache` |
| 12 | `test_settings_redis_backend_requires_url` | 異常 | `CACHE_BACKEND=redis` で `REDIS_URL` がないと起動時に検証エラー。エラーの文面に URL の値を含めない |
| 13 | `test_settings_cache_values_validated` | 異常/境界 | `CACHE_BACKEND` が `memory`・`redis` 以外、`CACHE_TTL_S` が 0・負のとき検証エラー。既定値は 900 |
| 14 | `test_service_miss_fetches_and_stores` | 正常 | 空のとき外部APIを 1 回呼び、`weather:tokyo` に保存される。`cached` は `false` |
| 15 | `test_service_hit_within_ttl_does_not_call_upstream` | 正常 | **受け入れ条件**。TTL 内の 2 回目は外部APIを呼ばない（`call_count` が 1 のまま）。`cached` は `true` |
| 16 | `test_service_hit_keeps_original_fetched_at` | 正常 | キャッシュから返すとき `fetched_at` は最初に取得した時刻（返した時刻ではない） |
| 17 | `test_service_ttl_boundary` | 境界 | 取得から TTL の 1 秒前は使う・ちょうどと 1 秒後は呼び直す（質問 8） |
| 18 | `test_service_refetch_after_expiry_overwrites` | 境界 | 期限切れ後は呼び直し、`fetched_at` が新しくなり、次の呼び出しはまた使われる |
| 19 | `test_service_cities_are_cached_separately` | 正常 | 東京を保存してもベルリンは外部APIを呼ぶ。キーは `weather:tokyo`・`weather:berlin` |
| 20 | `test_service_hit_reselects_hourly_by_now` | 境界 | 取得後、TTL 内で正時をまたいで返すとき、`hourly` の先頭が次の正時に進む。期待値は fixture の該当する行から読む |
| 21 | `test_service_upstream_failure_is_not_cached` | 異常 | 外部APIが失敗したら何も保存せず、次の呼び出しでまた外部APIを呼ぶ |
| 22 | `test_service_invalid_upstream_response_is_not_cached` | 異常 | 整形に失敗する応答（`current` の欠損など）は `UpstreamError` で、保存しない |
| 23 | `test_service_corrupted_entry_is_refetched`（JSON でない / 形が違う / `fetched_at` がない） | 異常 | 壊れた保存値はキャッシュなしとして扱い、呼び直して上書きする。500 にしない |
| 24 | `test_service_entry_from_future_is_refetched` | 境界 | `fetched_at` がいまより後の保存値は使わない |
| 25 | `test_service_entry_invalid_at_now_is_refetched` | 境界 | 保存時は通ったが、いまの時刻で選び直すと返す範囲に null が入る保存値は、呼び直す |
| 26 | `test_service_cache_read_failure_falls_back_to_upstream` | 異常 | `get` が `CacheError` でも外部APIから取得して返す。警告ログが出て、URL を含まない（質問 7） |
| 27 | `test_service_cache_write_failure_still_returns` | 異常 | `set` が `CacheError` でも応答は返る |
| 28 | `test_weather_second_request_is_cached`（tokyo / berlin） | 正常 | `GET /weather` を 2 回呼ぶと外部APIの呼び出しは 1 回。2 回目は `cached: true` で、`fetched_at` が 1 回目と同じ |
| 29 | `test_weather_shape_includes_cached_without_stale` | 正常 | 最上位のキーの集合が spec と一致。`stale` はない |
| 30 | `test_weather_invalid_city_does_not_touch_cache` | 異常 | 許可リスト外の `city` は 422 で、キャッシュの読み書きも外部呼び出しも起きない |
| 31 | `test_weather_upstream_error_then_success` | 異常 | 1 回目 502、2 回目に外部APIが直れば 200（失敗が保存されていない） |

- すべて `respx` でモックし、テストから外部APIを呼ばない。Redis も実物を使わない（`fakeredis`）。
- 時刻は `Clock` を差し替えて進める。テストで待たない。
- Red の確認：グループごと（メモリ → Redis → 設定・切り替え → サービス → ルーター）にテストを先に書き、失敗を実行して確かめてから実装する。

## 追加する依存パッケージ

| パッケージ | 理由 | 代替案 |
|---|---|---|
| `redis`（本番） | Redis に接続する公式の Python クライアント。非同期クライアントを含む | Redis を今回入れず、メモリとインターフェースだけにする（質問 1 の案 B） |
| `fakeredis`（開発） | 実物の Redis を起動せずに `RedisCache` をテストする。`redis` パッケージの本物の呼び出し方（`set` の `ex` など）を通るので、自作の偽物より確認として強い | (a) 自作の偽クライアントでテストする（依存は増えないが、`redis` パッケージの使い方の誤りを拾えない）。(b) CI で Redis のコンテナを起動して実物でテストする（手元では Docker が必要。CI の時間が増える） |

どちらも版と Python 3.14 対応は未確認。承認をもらえたら PyPI で確かめ、結果を示してから追加する。追加後に `pip-audit` を実行する。

## セキュリティ上の注意

- 入力検証：変更なし（`city` は Enum）。**キャッシュのキーは Enum の値から作る**。利用者の入力でキーの数が増えない（最大 2 つ）ので、キャッシュを埋めてメモリを使い切らせることができない。
- シークレット：`REDIS_URL` はパスワードを含みうるのでシークレットとして扱う。設定では値が表示されない型（`SecretStr` など）で持ち、ログ・エラーの文面・テストに値を出さない。`.env.example` には名前だけ。`.env` は読まない。`docker-compose.yml` に書くのは compose の中だけで通じる接続先（パスワードなし）で、秘密の値は書かない。
- 外部通信（ホスト・タイムアウト）：
  - Open-Meteo は #3・#4 のまま（`api.open-meteo.com`、接続 3 秒・全体 10 秒）。
  - Redis は設定の `REDIS_URL` のみ。利用者の入力から接続先を作らない。接続・読み書きのタイムアウトを必ず指定する（値は質問 5）。
  - Redis のポートは `docker-compose.yml` でホストに公開しない（compose 内のネットワークだけ）。
- キャッシュの中身を信用しない：読み出した値は JSON として読み直し、外部APIの応答と同じ厳しい検証を通す。`pickle` など、読み込みでコードが動く形式は使わない。
- エラー・ログ：キャッシュの失敗で内部の例外や接続先を応答に出さない。構造化ログに URL・保存値の全体を出さない。
- 依存：`redis`・`fakeredis` の追加（承認後）。

## 実行のたびに枠を使うものの見積もり

- 外部API（Open-Meteo）：手動確認で 2 都市 × 保存先 2 種類の **4 回**、予備を含めて **8 回以内**。fixture は #4 のものをそのまま使う（取り直さない）。テストからは 0 回。
- GitHub Actions：PR の作成で 1 回、レビュー後の修正と dev-log をまとめて 1 回の **計 2 回** を目安。

## リスク・未決事項

- **範囲が大きい**：インターフェース・メモリ・サービスへの組み込みに加えて、Redis・docker compose・依存 2 つが入る。実装はメモリを先に終わらせ（テスト 1〜4、10、13〜31）、Redis（5〜9、11、12、compose）を後にする。途中で分けたくなった場合に切りやすい順にしておく（質問 1）。
- **同時のリクエスト**：キャッシュが空・期限切れの瞬間に同じ都市へのリクエストが重なると、その数だけ外部APIを呼ぶ。受け入れ条件「TTL 内は外部APIを呼ばない」には当たらないと読んでいるが、解釈の確認が要る（質問 6）。
- **メモリキャッシュはプロセスごと**：uvicorn を複数ワーカーで動かすとワーカーごとに別のキャッシュになる（いまは 1 ワーカー）。再起動で消える。Redis に切り替える理由として記録する。
- **`current` も最大 15 分古くなる**：キャッシュから返すときの `current` は取得時点の値（`current.time` と `fetched_at` で分かる）。spec 6 の「まとめてキャッシュする」のとおり。
- **#6 との境目**：stale のためには保存先の期限を 6 時間に延ばす必要がある。今回は「新しいかどうか」をサービス側で判定する形にしておくので、#6 では保存先の期限と失敗時の分岐を足すだけで済む見込み。ただし #6 の計画で見直す。
- **`fakeredis` と実物の違い**：タイムアウトや接続の失敗は `fakeredis` では起こしにくい。テスト 8 は例外を差し込んで確かめ、実物での動作は手動確認（完了の確認 3）で見る。CI では実物の Redis を使ったテストは行わない。
- **p95 100ms（spec 10）**：自動テストでは測らない。手動確認のときに数回呼んで時間を見る程度にとどめ、結果を「実装時の変更」に書く。
- **Windows の手元環境**：`uv run uvicorn` はポリシーで起動できないため、手動確認は Docker で行う（#3・#4 と同じ）。
- **Issue #8 の本文を読めていない**（`gh` がこの環境にない）。spec の機能 #5 と同じ内容という前提。

## ブロッカー（人間の対応が必要なこと）

1. **依存パッケージの承認**（`redis`、`fakeredis`。質問 4）。CLAUDE.md「依存を追加するときは理由を説明して承認を得る」。
2. **Issue #8 の本文**：spec の機能 #5 にない要件が書かれていれば教えてください。

外部API表（spec 7）で新しく使う項目はありません（Open-Meteo の呼び出しは #4 のまま）。

## 質問

### 回答（2026-10-12 人間）

- 質問 1〜9：**すべて推奨どおり**。計画を承認。
  - 1：案 A。インターフェース＋メモリ＋Redis の実装と `docker-compose.yml` まで #5 に含める。
  - 2：`cached` は #5、`stale` は #6。
  - 3：整形前の応答を保存する。`hourly` は返すたびにその時刻で選び直し、`fetched_at` は外部APIから取得した時刻のまま。
  - 4：`redis`（本番）と `fakeredis`（開発）を追加してよい。版と Python 3.14 対応を PyPI で確かめて報告してから追加する。
  - 5：Redis のタイムアウトは接続・読み書きとも 1 秒（`REDIS_TIMEOUT_S` で変更可）。
  - 6：同時に来たリクエストをまとめる仕組みは今回入れない（リスクとして記録）。
  - 7：キャッシュが故障したときは、キャッシュなしとして外部APIを呼び 200 を返す（警告ログを残す）。
  - 8：15 分未満なら使う、15 分ちょうどから呼び直す。
  - 9：`CACHE_BACKEND`（既定 `memory`）、`CACHE_TTL_S`（既定 900）、`REDIS_URL`、`REDIS_TIMEOUT_S`。
- ブロッカー 1（依存の承認）：質問 4 の回答により承認済み。ブロッカー 2（Issue #8 の本文）：追加の要件の連絡なし。spec の機能 #5 と同じ内容として進める。

### 質問の内容

1. **今回の範囲**：受け入れ条件の「メモリ → Redis に切り替え可能」を、どこまでと読みますか。
   - 案 A（推奨）：共通のインターフェース＋メモリ＋ **Redis の実装と `docker-compose.yml` まで**。設定（`CACHE_BACKEND`）で切り替えられることをテストと手動確認で示す。2 つ目の保存先が実際にないと「切り替え可能」を確かめられないため。
   - 案 B：インターフェース＋メモリだけ。Redis と docker compose は別の Issue に分ける（PR は小さくなるが、spec の機能一覧に行を足す必要がある）。
2. **`cached` をどの機能で入れるか**（spec 5 で #5・#6 の計画に委ねられている。#3 のとき AI が推測で割り振って直した経緯があるので確認します）。推奨：**`cached` は #5、`stale` は #6**。`cached` はキャッシュから返したとき `true`、外部APIから取得したとき `false`。
3. **キャッシュから返すときの `hourly` と `fetched_at`**：推奨は、整形前の応答を保存し、**`hourly` は返すたびにその時刻で選び直す**、**`fetched_at` は外部APIから取得した時刻のまま**。別案：整形後の応答を保存してそのまま返す（単純だが、正時をまたぐと過ぎた時刻が `hourly` の先頭に最大 15 分残る）。
4. **依存の追加**：`redis`（本番）と `fakeredis`（開発）を追加してよいですか（版と Python 3.14 対応は、承認後に PyPI で確かめて報告してから追加します）。`fakeredis` を避ける場合は、自作の偽クライアント（案 a）と CI での実物（案 b）のどちらにしますか。
5. **Redis のタイムアウト**：spec に値がありません（spec 7 の「接続 3 秒・全体 10 秒」は外部API向け）。推奨は **接続・読み書きとも 1 秒**（環境変数 `REDIS_TIMEOUT_S` で変更可）。キャッシュが遅いときは待たずに外部APIへ進むほうがよいため。
6. **同時に来たリクエストのまとめ**：キャッシュが空のときに同じ都市へ同時に来たリクエストを、1 回の外部呼び出しにまとめる仕組み（都市ごとのロック）を入れますか。推奨は **今回は入れない**（spec にない。Open-Meteo の上限 600 回/分に対して手元の利用では問題にならない。リスクとして記録）。
7. **キャッシュが故障したとき**（Redis に接続できないなど）：推奨は **キャッシュなしとして外部APIを呼び、200 を返す**（警告ログを残す）。別案：502 や 503 にする（spec のエラー表に該当する code がない）。
8. **TTL の境界**：取得からちょうど 15 分 0 秒のときは期限切れ（呼び直す）としてよいですか。推奨は「15 分未満なら使う、15 分ちょうどから呼び直す」。
9. **環境変数の名前と既定値**：`CACHE_BACKEND`（既定 `memory`）、`CACHE_TTL_S`（既定 900）、`REDIS_URL`、`REDIS_TIMEOUT_S` でよいですか。既定を `memory` にするのは、Redis なしでも `uv run pytest` と単体の起動ができるようにするためです（`docker-compose.yml` では `redis` を指定します）。

## 実装時の変更

- **依存の版**（2026-10-12、PyPI で確認してから追加）：`redis` 8.1.0（Python 3.10 以上、3.14 の分類あり）、`fakeredis` 2.39.0（3.14 の分類あり。`redis>=4.3` と `sortedcontainers` に依存）。追加後の `pip-audit` は問題なし。
- **実行して確かめたライブラリの使い方**：
  - `redis.asyncio.Redis.from_url(url, socket_timeout=, socket_connect_timeout=, decode_responses=True)` は作るだけでは接続しない。`get` はないキーで `None`、`set(key, value, ex=秒)` で期限が付く（`ttl` で 900）。閉じるのは `aclose()`。
  - 接続できないときの例外は `redis.exceptions` の `ConnectionError`・`TimeoutError` で、どちらも `RedisError` の子。タイムアウト 1 秒のとき、届かない接続先への `get` は約 1.02 秒で失敗した（何度も再試行して数秒かかる、ということはなかった）。
  - `fakeredis.FakeAsyncRedis` は `redis.asyncio.Redis` のインスタンスとして扱える。`FakeServer().connected = False` で接続の失敗を起こせる。FastAPI の `TestClient` の中と外（別のイベントループ）から同じインスタンスを使えた。
- **Redis のイメージ**：`redis:8.10.2-alpine`（2026-10-12 に Docker Hub の公式イメージの一覧で、その時点の最新の版として確認）。
- **Red の確かめ方**：最初の Red は、5 つのテストファイルが `No module named 'app.cache'` で収集エラーになり、個々のテストの失敗理由を見られなかった。そこで実装の前に「何もしない骨組み」（常に `None` を返すキャッシュ、キャッシュを使わないサービス）を置いて実行し、59 件が失敗・それ以外が通ることを見た。
  - 骨組みでも通ったテスト（「保存しない」「使わない」を確かめる種類のもの。キャッシュが何もしなければ当然通る）は、実装後に **実装をわざと壊して失敗することを確かめた**（7 通り。確認後に元へ戻し、354 件が通ることを確認）：
    1. 取得時刻が未来の保存値を使う → `test_service_entry_from_future_is_refetched` が失敗
    2. TTL ちょうども使う → `test_service_ttl_boundary[900]`、`test_service_respects_configured_ttl`、`test_weather_refetches_after_ttl` が失敗
    3. 保存値を整形し直せないときの呼び直しを外す → `test_service_entry_invalid_at_now_is_refetched` ほか 1 件が失敗
    4. キャッシュの読み出し失敗を拾わない → `test_service_cache_read_failure_falls_back_to_upstream`、`test_weather_cache_failure_still_returns_200` が失敗
    5. 整形の前に保存する → `test_service_invalid_upstream_response_is_not_cached` の 3 件が失敗
    6. `REDIS_URL` を普通の文字列で持つ → `test_settings_do_not_show_redis_url` ほか 1 件が失敗（このテストは最初の Red では実装前から通っていた）
    7. キャッシュから返すときに `hourly` を取得時刻で選ぶ → `test_service_hit_reselects_hourly_by_now` ほか 1 件が失敗
  - **壊して確かめていないもの**：`test_service_upstream_failure_is_not_cached`、`test_weather_upstream_error_then_success`（失敗を保存する実装は、自然な壊し方がなく試していない）、`test_weather_invalid_city_does_not_touch_cache`（検証は FastAPI が先に行うため、キャッシュに触る経路がない）。
- **計画から足したテスト**：ルーターで保存先を `fakeredis` の Redis に替えても同じ動きになること（`test_weather_second_request_is_cached` の `redis`）、キャッシュが故障しても 200 が返ること（ルーター）、設定した TTL が効くこと、既定の保存先がメモリであること、キャッシュから返した応答のキーが spec と同じこと、期限切れの後にメモリへ入れ直せること、Redis の例外の文面に接続先が出ないこと、タイムゾーンのない取得時刻を壊れた保存値として扱うこと。計 354 件（#4 の終わりは 270 件）。
- **計画の表になかった既存テストの変更**：
  - `test_weather_returns_hourly_and_daily_shape` の `"cached" not in body` を `body["cached"] is False` に変えた（`cached` を #5 で入れると決まったため）。`stale` がないことの確認は残した。
  - `test_settings_defaults_match_spec` に、キャッシュの設定の既定値の確認を足した。
  - `tests/conftest.py` に `FakeClock`（時刻を進められる時計）を足した。`client` の fixture は変えていない。
  - `build_weather_response(city, raw, FIXED_NOW)` の約 55 か所は、計画どおり変えていない。
- **設計で決めた細部**：
  - 保存する取得時刻は、タイムゾーン付きの ISO 8601 だけを受け付ける（数値、タイムゾーンなしは壊れた保存値として扱う）。
  - `fetched_at` は、外部APIの応答を受け取った後の時刻（#4 までと同じ）。
  - `RedisCache` は Redis の例外を `CacheError("redis get failed")` のように包み、元の例外をつなげない（元の文面に接続先が入りうるため）。ログには例外の型の名前だけを出す。
  - TTL は `Settings` をルーターの依存として受け取って渡している。
  - Redis への全体のタイムアウト（`asyncio.timeout`）は足していない。実測で 1 秒のタイムアウトどおりに失敗したため。
- **`.env.example` を更新できていない**：`.claude/settings.json` の `Read(./.env.*)` の拒否が `.env.example` にも当たり、書き込めなかった。迂回はしていない。**人間の対応が必要**（追記する内容：`CACHE_BACKEND`、`CACHE_TTL_S`、`REDIS_URL`、`REDIS_TIMEOUT_S` の名前だけ）。
  - 計画の作成中に、AI が `cat .env.example` をシェルから実行して中身（コメント 2 行、変数なし）を読んでいた。拒否の設定を通らない経路だったことに後から気づいた。中身に秘密はなかったが、今後は `.env*` をシェルからも読まない。
- **手動確認**（2026-10-12T19:18Z ごろ、Docker）：
  - `docker compose up --build`（API + Redis）：`/weather?city=tokyo`・`berlin` とも 1 回目 `cached: false`、2 回目 `cached: true` で `fetched_at` が同じ。Redis に `weather:tokyo`・`weather:berlin` があり、残り時間は 896 秒（期限付き）。
  - キャッシュから返すときの応答時間：10 回で 9〜17 ミリ秒（spec 10 の目安は p95 100ms。回数が少ないので目安として）。1 回目（外部APIあり）は 332 ミリ秒。
  - Redis を止めた状態：200、`cached: false`、応答まで約 1.2 秒。警告ログが 4 行（Redis 側と、サービス側で読み・書きそれぞれ）。URL は出ていない。
  - `CACHE_BACKEND` を指定しない（メモリ）コンテナ：1 回目 `false`、2 回目 `true`。
  - `uv run uvicorn` での確認はしていない（#3・#4 と同じく Docker を使った）。
- **外部APIの呼び出し回数**：手動確認の 4 回（見積もりは 8 回以内）。fixture は取り直していない。
- **残っているリスク**：
  - Redis が止まっている間は、リクエストごとに読み・書きのそれぞれでタイムアウトを待つ（今回は合計で約 1 秒、最大で約 2 秒）。そのうえ毎回外部APIを呼ぶ。
  - キャッシュの失敗 1 回につき警告ログが 2 行出る（`app.cache.redis` と `app.services.weather`）。
  - 同時に来たリクエストはまとめていない（質問 6 の決定どおり）。
  - CI では実物の Redis を使ったテストをしていない。`docker-compose.yml` は CI で起動していない。
- **後の機能への申し送り**：
  - **#6 エラー処理**：stale を返すには、保存先の期限（いまは TTL と同じ 15 分）を 6 時間に延ばす必要がある。新しいかどうかはサービス側（`_is_fresh`）で判定しているので、保存先の期限と、外部API失敗時の分岐を足す形になる見込み。`stale` のキーも #6 で足す。
  - **#14 CD**：スモークテストで `docker-compose.yml` を使うかどうかを決める。
- **レビュー後の変更**（2026-10-12、人間の回答「推奨でお願いします」）：
  - **設定値の受け渡しのテストを 2 件足した**。どちらも、値を直書きに変えても既存のテストが通ってしまう状態だった（骨組みの段階でルーターに `900` を直書きしていたとき、`test_weather_refetches_after_ttl` は通っていた）。
    - `test_weather_uses_configured_ttl`：設定の TTL を 60 秒にして、59 秒で `cached: true`、60 秒で呼び直すこと。
    - `test_build_cache_passes_url_and_timeout_to_redis_client`：`REDIS_TIMEOUT_S` と `REDIS_URL` が、クライアントを作る関数まで届くこと。
  - **`test_redis_non_text_value_becomes_cache_error` を足した**（文字列に直さない設定のクライアントがバイト列を返したとき `CacheError`。未カバーだった 1 行）。
  - 実装が先にあるテストなので、**実装をわざと壊して失敗することを確かめた**（確認後に元へ戻した）：TTL を `900` に直書き → 1 件目が失敗。タイムアウトを `1.0` に直書き → 2 件目が失敗。文字列以外もそのまま返す → 3 件目が失敗。
  - **`test_service_upstream_failure_is_not_cached` も壊して確かめた**：外部APIの失敗を拾って空の値を保存するようにすると、3 件とも失敗した。
    - 同じ壊し方では `test_weather_upstream_error_then_success` は **失敗しなかった**（保存された空の値は「壊れた保存値」として捨てられ、呼び直して 200 になるため）。このテストが失敗するのは「失敗そのものを応答として保存して返す」実装のときだけで、そこまでは試していない。
    - `test_weather_invalid_city_does_not_touch_cache` は、検証を FastAPI が先に行いキャッシュに触る経路がないため、壊して確かめていない。
  - 実装のコード（`app/`）はレビュー後に変えていない。計 357 件、カバレッジ 99.05%。
  - **今回は扱わないと決めたもの**：NaN を含む応答が検証を通る問題（#3・#4 からある。`current.temperature_2m` が NaN の応答は 200 になり `temperature_c: null` が返ることを実行して確かめた。キャッシュには null で保存され、その間は毎回呼び直しになる）。別の Issue にする。
  - **未解決**：`.env.example` の追記（人間の対応待ち）。`docs/spec.md` の「#5 で決めたこと」のうち、質問への回答ではなく計画の「設計の要点」から書いた 2 項目（整形に成功した応答だけを保存する／読めない保存値は呼び直す）は、そのまま残している。
  - Redis のイメージ `8.10.2-alpine` は、レビューで Docker Hub の `alpine` タグと同じダイジェストであることを確かめた（上の「最新の版として確認」は、実装時点では番号の大小から判断しただけだった）。
