# 仕様書（spec.md）

最終更新：2026-10-12　／　状態：初版（天気予報の拡張・日照計算を追加）

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
- 上の数値は形式を示す例で、実在の観測値ではない。

**天気の分類（`weather`）**

Open-Meteo の天気コード（WMO の天気コード）を、アプリで扱いやすい分類に変換する。
対応表は **公式ドキュメントで確認してから** `app/services/weather_codes.py` に実装し、ここに表を追記する。

| weather | 意味 |
|---|---|
| `clear` | 快晴 |
| `partly_cloudy` | 晴れ時々曇り |
| `cloudy` | 曇り |
| `fog` | 霧 |
| `drizzle` | 霧雨 |
| `rain` | 雨 |
| `snow` | 雪 |
| `thunderstorm` | 雷雨 |
| `unknown` | 対応表にないコード（エラーにせずこれを返し、ログに残す） |

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

## 7. 外部API・データ

**実装前に公式ドキュメントで確認し、「状態」を更新すること。未確認の項目は使わない。**

| 用途 | 提供元 | エンドポイント・項目（候補） | 利用条件・制限 | 状態 |
|---|---|---|---|---|
| 予報（現在・時間） | Open-Meteo Forecast | `api.open-meteo.com/v1/forecast`、temperature_2m, apparent_temperature, dew_point_2m, relative_humidity_2m, precipitation, precipitation_probability, weather_code, cloud_cover, cloud_cover_low/mid/high, pressure_msl, wind_speed_10m | 要確認 | 未確認 |
| 予報（日ごと） | Open-Meteo Forecast | 同上、daily：weather_code, temperature_2m_max/min, precipitation_sum, precipitation_probability_max, sunrise, sunset | 要確認 | 未確認 |
| 予報のオプション | Open-Meteo Forecast | 風速の単位指定（m/s）、タイムゾーン指定、予報日数の指定 | 要確認 | 未確認 |
| 天気コード表 | Open-Meteo / WMO | weather_code の各値の意味 | — | 未確認 |
| 太陽位置の計算式 | NOAA Solar Calculator | 計算式・大気差の扱い（実装の根拠として出典を記録） | — | 未確認 |
| 過去の気象 | Open-Meteo Historical | `archive-api.open-meteo.com/v1/archive`、上と同じ項目 | 要確認 | 未確認 |
| METAR過去データ | Iowa Environmental Mesonet | ASOS/METAR ダウンロード、雲量（skyc1〜4）・雲高（skyl1〜4、フィート） | 要確認 | 未確認 |

- 外部通信のタイムアウト：接続 3 秒、全体 10 秒。リトライは最大 2 回（指数バックオフ）。
- 通信先は上表のホストのみ。

## 8. Discord 通知

- 毎朝 07:00（JST）に、東京・ベルリンの次の内容を送る：
  今日の天気・最高/最低気温・降水確率、日の出・日の入り、昼の長さと暗い時間、雲底高度予測。
- GitHub Actions の schedule でコンテナを実行する。
- Webhook URL は GitHub Secrets（`DISCORD_WEBHOOK_URL`）に保存し、ログに出さない。
- 送信失敗時はジョブを失敗させ、Actions 上で気づけるようにする。

## 9. 雲底高度予測（ML）

### 目的変数

- METAR の最も低い BKN または OVC 層の高さ（シーリング）をメートルに変換した値。
- **シーリングなし（雲が少ない・ない）の扱いは EDA で決める**。候補：上限値で打ち切る／「低い雲があるか」の分類と、ある場合の回帰に分ける。

### 特徴量（候補）

気温、露点、気温と露点の差、相対湿度、海面気圧、風速、層別雲量、時刻・季節（周期表現）、太陽高度（`app/services/solar.py` の計算を共有）、都市。

### ベースライン

`125 × (気温 − 露点)` [m]。モデルはこれに勝つことが前提。

### 分割と評価

- 時系列分割：学習 2018〜2023、検証 2024、テスト 2025（データ量を見て調整）。ランダム分割はしない。
- 指標：MAE（m）。都市別・季節別にも算出する。分類にする場合は F1 も見る。
- 成功基準：EDA 後に決め、ここに追記する（例：テストでベースラインより MAE を X% 改善）。

### リーク・ずれ対策

- 予測時点より後の情報を特徴量に使わない。
- 学習は過去データ、推論は予報データを使うため、その差の影響を `docs/model-card.md` に記録する。
- 特徴量作成は `ml/features.py` のみに実装し、学習と推論で共有する。

### ノートブック

| ファイル | 内容 | 成果物 |
|---|---|---|
| `01_data_fetch.ipynb` | METAR・Open-Meteo の取得と時刻結合 | `data/processed/*.parquet` |
| `02_eda.ipynb` | 欠損、分布、季節差、都市差、露点差との関係 | `docs/eda.md`（要約） |
| `03_baseline.ipynb` | ベースライン評価、評価関数の確定 | `reports/baseline.json` |
| `04_train.ipynb` | 学習 | `models/cloud_base.joblib` |
| `05_evaluate.ipynb` | テスト評価、都市別・季節別 | `reports/metrics.json`、`docs/model-card.md` |

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
| `ci.yml` | PR | ruff、mypy、pytest（カバレッジ 80% 未満で失敗）、pip-audit、docker build。nbmake は最初のノートブック（#8）で追加する |
| `cd.yml` | main へのマージ・タグ | イメージをビルド → コンテナ起動してスモークテスト → ghcr.io へ push |
| `notify.yml` | schedule（毎朝） | コンテナを実行して Discord に通知 |

## 14. 機能一覧とマイルストーン

| # | 機能 | 受け入れ条件 | 状態 |
|---|---|---|---|
| 1 | 雛形 | `/health` が 200、pytest・ruff・mypy が通る、Dockerfile でビルドできる | 完了 |
| 2 | CI | PR で ci.yml が実行され、失敗時に PR がマージできない | 進行中（ci.yml 導入済み。PR での実行確認とブランチ保護の設定が残っている） |
| 3 | 天気取得（現在） | `/weather` の `current` が仕様どおり。天気コードの分類（未知コードは `unknown`）。外部APIはモックでテスト | 未着手 |
| 4 | 天気予報（時間・日） | `hourly` 24件・`daily` 7日分が仕様どおり。日付は現地の日付で区切られる | 未着手 |
| 5 | キャッシュ | TTL 内は外部APIを呼ばない。メモリ → Redis に切り替え可能 | 未着手 |
| 6 | エラー処理 | タイムアウト・5xx でリトライ、stale 返却、502 の各テストが通る | 未着手 |
| 7 | 日照・暗い時間 | `/daylight` が仕様どおり。Open-Meteo の日の出入りと ±2 分以内。境界のケースのテストが通る | 未着手 |
| 8 | データ取得 | `01_data_fetch` で両都市のデータを取得・結合できる | 未着手 |
| 9 | EDA | `02_eda` 完了、シーリングなしの扱いを決定し `docs/eda.md` に記録 | 未着手 |
| 10 | ベースライン | `03_baseline` で都市別 MAE を算出、評価関数をテスト付きで `ml/` に実装 | 未着手 |
| 11 | 学習・評価 | `04`・`05` 完了、ベースラインとの比較を `docs/model-card.md` に記録 | 未着手 |
| 12 | 推論API | `/cloud-base` が仕様どおりに返る。モデルなしで 503 | 未着手 |
| 13 | Discord通知 | 毎朝通知が届く（天気・日照・雲底）。Webhook URL がログに出ない | 未着手 |
| 14 | CD | main マージでスモークテスト後に ghcr.io へ push される | 未着手 |
| 15 | UI（任意） | 現在の天気・予報・日照・雲底を表示する簡単な画面 | 未着手 |

## 15. AI駆動開発の記録

日々の記録は `docs/dev-log.md` に置く。ある程度溜まったら、観点別（プロンプト・コンテキスト・コスト・誤り対策・品質評価・安全性・TDD）のまとめを別途作る。
