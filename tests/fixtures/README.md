# tests/fixtures

外部APIの実際の応答を保存したもの。テストの期待値はここから読む（AIが値を作らない）。
応答は加工せず、取得したままの内容で保存している。

| ファイル | 取得日時（UTC） | 取得方法 |
|---|---|---|
| `open_meteo/forecast_tokyo.json` | 2026-10-12T15:02:12Z | `curl`、下の URL（`latitude=35.55&longitude=139.78`、`timezone=Asia/Tokyo`、`timeformat=unixtime`） |
| `open_meteo/forecast_tokyo_iso8601.json` | 2026-10-12T15:02:12Z | 同上で `timeformat` の指定なし（時刻が現地時刻の文字列になる） |
| `open_meteo/forecast_berlin.json` | 2026-10-12T15:02:13Z | `curl`、下の URL（`latitude=52.36&longitude=13.50`、`timezone=Europe/Berlin`、`timeformat=unixtime`） |
| `open_meteo/forecast_berlin_iso8601.json` | 2026-10-12T15:02:13Z | 同上で `timeformat` の指定なし |

```
https://api.open-meteo.com/v1/forecast?latitude=<緯度>&longitude=<経度>&current=temperature_2m,apparent_temperature,dew_point_2m,relative_humidity_2m,precipitation,weather_code,cloud_cover,cloud_cover_low,cloud_cover_mid,cloud_cover_high,wind_speed_10m&hourly=temperature_2m,precipitation_probability,precipitation,weather_code,cloud_cover,cloud_cover_low,cloud_cover_mid,cloud_cover_high&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,sunrise,sunset&wind_speed_unit=ms&forecast_days=7&timezone=<タイムゾーン>&timeformat=unixtime
```

## `/weather` の入力（#25 の追加で取り直したもの）

`/weather` の `hourly` に風速（`wind_speed_ms`）を足すため、いまのアプリ（`app/clients/open_meteo.py`）と同じ URL で取り直した（応答は取得したまま）。
`/weather` のテストは、上の 4 つではなく、こちらを使う（`tests/conftest.py` の `load_forecast`・`load_forecast_iso8601`）。
上の 4 つは、「4 項目のない保存値」のテスト（`load_legacy_forecast`・`LEGACY_NOW`）に残している。

| ファイル | 取得日時（UTC） | 取得方法 |
|---|---|---|
| `open_meteo/forecast_tokyo_wind.json` | 2026-10-19T18:25:57Z〜18:25:58Z | `curl`、下の URL（`latitude=35.55&longitude=139.78`、`timezone=Asia/Tokyo`、`timeformat=unixtime`） |
| `open_meteo/forecast_tokyo_wind_iso8601.json` | 同上 | 同上で `timeformat` の指定なし |
| `open_meteo/forecast_berlin_wind.json` | 2026-10-19T18:25:57Z | `curl`、下の URL（`latitude=52.36&longitude=13.5`、`timezone=Europe/Berlin`、`timeformat=unixtime`） |
| `open_meteo/forecast_berlin_wind_iso8601.json` | 同上 | 同上で `timeformat` の指定なし |

```
https://api.open-meteo.com/v1/forecast?current=temperature_2m,apparent_temperature,dew_point_2m,relative_humidity_2m,precipitation,weather_code,cloud_cover,cloud_cover_low,cloud_cover_mid,cloud_cover_high,wind_speed_10m&hourly=temperature_2m,precipitation_probability,precipitation,weather_code,cloud_cover,cloud_cover_low,cloud_cover_mid,cloud_cover_high,dew_point_2m,relative_humidity_2m,pressure_msl,wind_speed_10m,sunshine_duration,direct_radiation,diffuse_radiation&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,sunrise,sunset&wind_speed_unit=ms&forecast_days=7&past_hours=24&forecast_hours=168&latitude=<緯度>&longitude=<経度>&timezone=<タイムゾーン>[&timeformat=unixtime]
```

- 4 つとも 200。`hourly` は 192 行で null はない。先頭は 2 都市とも 2026-10-18T18:00Z、最後は 2026-10-26T17:00Z。`hourly_units.wind_speed_10m` は `m/s`。
- `current.time` は 2026-10-19T18:15Z。東京の `daily` の先頭は 2026-10-20、ベルリンは 2026-10-19（7 日の間に夏時間の終わり 10-25 をまたぐ）。
- `tests/conftest.py` の `FIXED_NOW` を取得時刻の直後（2026-10-19T18:26:00.123456Z）に合わせている。取り直したら変える。

## 雲底高度の予測（#12 推論API）の入力

`/cloud-base` は、`hourly` に 4 項目（`dew_point_2m`・`relative_humidity_2m`・`pressure_msl`・`wind_speed_10m`）を
足した応答を使う。上の 4 つの fixture は足す前の形のまま残し（`/weather` のテストと、「4 項目のない保存値」の
テストに使う）、足した後の形を別に取得した。応答は取得したまま。

| ファイル | 取得日時（UTC） | 取得方法 |
|---|---|---|
| `open_meteo/forecast_tokyo_cloud_base.json` | 2026-10-13T14:16:25Z | `curl`、上の URL の `hourly=` の末尾に `,dew_point_2m,relative_humidity_2m,pressure_msl,wind_speed_10m` を足したもの（`latitude=35.55&longitude=139.78`、`timezone=Asia/Tokyo`、`timeformat=unixtime`） |
| `open_meteo/forecast_berlin_cloud_base.json` | 2026-10-13T14:16:29Z | 同上で `latitude=52.36&longitude=13.50`、`timezone=Europe/Berlin` |

- `hourly` は 168 行で null はない。東京の先頭は 2026-10-12T15:00Z（現地の 10-13 の 0 時）、ベルリンは 2026-10-12T22:00Z。
- `tests/conftest.py` の `CLOUD_BASE_NOW` を取得時刻に合わせている。取り直したら変える。
- 東京の先頭の行（2026-10-12T15:00Z）は、上の古い fixture の取得時刻（`LEGACY_NOW`。#25 の追加の前は `FIXED_NOW`）の正時と同じ。
  「4 項目のない保存値があるときに呼び直す」テストがこれに頼っているので、取り直すときは気をつける。

## 過去 24 時間の雲量（#15 UI）の入力

`/cloud-history` のために、#12 の URL に `past_hours=24&forecast_hours=168` を足した応答（応答は取得したまま）。

| ファイル | 取得日時（UTC） | 取得方法 |
|---|---|---|
| `open_meteo/forecast_tokyo_past.json` | 2026-10-14T09:18:03Z | `curl`、#12 の URL（`hourly=` に 4 項目を足したもの）の末尾に `&past_hours=24&forecast_hours=168`（`latitude=35.55&longitude=139.78`、`timezone=Asia/Tokyo`、`timeformat=unixtime`） |
| `open_meteo/forecast_berlin_past.json` | 2026-10-14T09:18:03Z | 同上で `latitude=52.36&longitude=13.50`、`timezone=Europe/Berlin` |

- `hourly` は 192 行（過去 24 ＋ 先 168）で null はない。先頭は 2 都市とも 2026-10-14T09:00Z（取得時の UTC の正時）の 24 時間前＝2026-10-13T09:00Z、最後は 2026-10-21T08:00Z。
  現地の 0 時から始まらない（`past_hours`・`forecast_hours` は「現在の時刻」が基準。公式ドキュメントのとおり）。
- `daily` は 7 行のまま（先頭は現地の今日）。`current.time` は 2026-10-14T09:15Z。

## 日差し（#15 UI の `/sunshine`）の入力

上の「過去 24 時間の雲量」の URL の `hourly=` の末尾に `,sunshine_duration,direct_radiation,diffuse_radiation` を足した応答（応答は取得したまま）。

| ファイル | 取得日時（UTC） | 取得方法 |
|---|---|---|
| `open_meteo/forecast_tokyo_sun.json` | 2026-10-14T12:20:49Z〜12:20:54Z | `curl`、上の URL に 3 項目を足したもの（`latitude=35.55&longitude=139.78`、`timezone=Asia/Tokyo`、`timeformat=unixtime`） |
| `open_meteo/forecast_berlin_sun.json` | 2026-10-14T12:20:54Z〜12:21:02Z | 同上で `latitude=52.36&longitude=13.50`、`timezone=Europe/Berlin` |

- `hourly` は 192 行で null はない。先頭は 2 都市とも 2026-10-13T12:00Z、最後は 2026-10-21T11:00Z。3 項目はどれも小数（`sunshine_duration` は `s`、日射は `W/m²`）。
- `tests/conftest.py` の `SUN_NOW` を取得時刻の直後に合わせている。取り直したら変える。

## 太陽計算（#7 日照）の期待値

`/daylight` は外部APIを呼ばない。下のファイルは、計算結果を比べる相手として 1 回だけ取得したもの。
読み出しは `tests/solar_refs.py` にまとめている。

| ファイル | 取得日時（UTC） | 取得方法・内容 |
|---|---|---|
| `open_meteo/sun_<city>_16days.json` | 2026-10-12T20:25:16Z | `curl`、`api.open-meteo.com/v1/forecast?latitude=<緯度>&longitude=<経度>&daily=sunrise,sunset&forecast_days=16&timezone=<タイムゾーン>&timeformat=unixtime`。ベルリンは夏時間が終わる日（2026-10-25）を含む |
| `open_meteo/archive_sun_<city>.json` | 2026-10-12T20:25:17Z | `curl`、`archive-api.open-meteo.com/v1/archive?latitude=<緯度>&longitude=<経度>&daily=sunrise,sunset&start_date=2025-12-21&end_date=2026-06-21&timezone=<タイムゾーン>&timeformat=unixtime`。冬至（2025-12-21）・春分（2026-03-20）・夏至（2026-06-21）と、ベルリンの夏時間が始まる日（2026-03-29）を含む 183 日 |
| `usno/year_2026_<city>_<civil\|nautical\|astronomical>.html` | 2026-10-12T20:25:26Z〜38Z | `curl`、`aa.usno.navy.mil/calculated/rstt/year?ID=AA&year=2026&task=<2\|3\|4>&lat=<緯度>&lon=<経度>&label=<名前>&tz=<9\|1>&tz_sign=1&submit=Get+Data`。米国海軍天文台（USNO）の薄明の表。**分単位、現地の標準時**（東京 UTC+9、ベルリン UTC+1。夏時間ではない）。`////` はその高度まで沈まない日 |
| `usno/oneday_<city>_<日付>.json` | 同上 | `curl`、`aa.usno.navy.mil/api/rstt/oneday?date=<日付>&coords=<緯度>,<経度>&tz=0`。南中（Upper Transit）を使う。**分単位、UT** |
| `noaa/solar_calculations_day.json` | 2026-10-12（ファイルの取得） | `gml.noaa.gov/grad/solcalc/NOAA_Solar_Calculations_day.ods` の「Calculations」シートから、入力セル・1 行目の式・**NOAA が計算して保存していた値**（北緯 40°・西経 105°・UTC−7・2010-06-21 の 6 分おき 240 行）を取り出したもの。値は変えていない。元の .ods（約 250 KB）はリポジトリに入れていない |

- Open-Meteo の応答は取得したまま。USNO の HTML も取得したまま（表の部分だけをテストで読む）。
- USNO の表の `ID=AA` は画面の既定値をそのまま使った。USNO の API の説明は「AA は内部用なので避ける」としているので、取り直すときは別の ID にする。
- Open-Meteo の応答に入っている緯度・経度は、送った値（spec の値）と少し違う（格子点の座標）。計算は spec の値で行う。
- 出典：USNO Astronomical Applications Department（https://aa.usno.navy.mil/）、NOAA Global Monitoring Laboratory（https://gml.noaa.gov/grad/solcalc/）。

## 学習データ（#8 データ取得）の生データのサンプル

`data_raw/` は、ノートブック `01_data_fetch` が保存する生データ（`data/raw/`）と同じ並び
（`<提供元>/<city>_<年>.<拡張子>`）で置いてある。**ファイル名は 2025 年だが、中身は 2025-01-15〜16 の 2 日ぶんだけ**。
テストの期待値と、ノートブックのサンプル実行（nbmake・CI）の入力の両方に使う。応答は取得したまま。

| ファイル | 取得日時（UTC） | 取得方法 |
|---|---|---|
| `data_raw/iem/tokyo_2025.csv`（RJTT）、`berlin_2025.csv`（EDDB） | 2026-10-12T20:50Z | `curl`、`mesonet.agron.iastate.edu/cgi-bin/request/asos.py?station=<ICAO>&data=tmpf,dwpf,relh,drct,sknt,alti,mslp,vsby,skyc1,skyc2,skyc3,skyc4,skyl1,skyl2,skyl3,skyl4,wxcodes,metar&sts=2025-01-15T00:00:00Z&ets=2025-01-17T00:00:00Z&tz=UTC&format=onlycomma&missing=empty&trace=empty&report_type=3&report_type=4` |
| `data_raw/open_meteo_archive/berlin_2025.json` | 2026-10-12T20:50Z | `curl`、`archive-api.open-meteo.com/v1/archive?latitude=52.36&longitude=13.50&hourly=temperature_2m,dew_point_2m,relative_humidity_2m,pressure_msl,precipitation,weather_code,cloud_cover,cloud_cover_low,cloud_cover_mid,cloud_cover_high,wind_speed_10m&start_date=2025-01-15&end_date=2025-01-16&wind_speed_unit=ms&timeformat=unixtime` |
| `data_raw/open_meteo_archive/tokyo_2025.json` | 2026-10-12T20:53:22Z | 同上で `latitude=35.55&longitude=139.78` |

- METAR は、アプリが要求する列（`tmpf`・`dwpf`・`vsby`・`skyc1〜4`・`skyl1〜4`・`wxcodes`・`metar`）より多い列で取得してある
  （調査のときの応答をそのまま使ったため。`relh`・`drct`・`sknt`・`alti`・`mslp` が余分）。整形は必要な列だけを使う。
- METAR の値は華氏・マイル・フィート。時刻は UTC（`YYYY-MM-DD HH:MM`）。欠損は空文字。
- 東京は毎時 0 分・30 分と臨時の報告、ベルリンは毎時 20 分・50 分。高さのない雲の層（電文の `SCT///`）を含む。
- 出典：Iowa Environmental Mesonet, Iowa State University（https://mesonet.agron.iastate.edu/ 。パブリックドメイン）、
  Weather data by Open-Meteo.com（CC BY 4.0）。

## 2 種類ある理由

- `forecast_<city>_wind.json`（いまの `/weather` のテスト）・`forecast_<city>.json`（#12 より前の形）：アプリが実際に受け取る形（時刻が UNIX 秒）。
- `forecast_<city>_wind_iso8601.json`・`forecast_<city>_iso8601.json`：それぞれ同じ時刻に、時刻形式だけ変えて取得したもの。`daily.time` に
  Open-Meteo が区切った **現地の日付** が文字列で入っているので、日付の期待値として使う。
  時刻以外の値は 2 つのファイルで一致している（`_wind` の組は 2026-10-19 に `current`・`hourly`・`daily` を比べて確かめた）。

## 取得した時刻について

- 東京は、**現地の日付が UTC の日付より進んでいる時刻** に取得している。
  「日付を UTC ではなく現地で区切る」ことを確かめるため。
  `_wind` の組は現地 10-20 03:25 ごろ（UTC 10-19）、古い組は現地 10-13（UTC 10-12）。
- ベルリンは同じ時刻で、現地と UTC の日付は同じ（`_wind` の組は現地 10-19 20:25 ごろ、古い組は現地 10-12 17:02）。
- `hourly` の 24 件は時計に依存するため、`tests/conftest.py` の `FIXED_NOW`（`_wind` の組）と `LEGACY_NOW`（古い組）を取得時刻に合わせている。
  fixture を取り直したら、これらも変える。

出典：[Weather data by Open-Meteo.com](https://open-meteo.com/)（CC BY 4.0）

## DAST（#23）の ZAP のレポート

`scripts/zap_high_alerts.py` のテストに使う。外部 API の応答ではなく、手元で ZAP を実行して得たレポート（取得したまま）。
High・Medium の警告を含むレポートは、テストの中でこのファイルを写して `riskcode` などを書き換えて作る（ファイルには保存しない）。

| ファイル | 作成日時（UTC） | 作成方法 |
|---|---|---|
| `zap/api_scan_2.17.0.json` | 2026-10-16T17:54:21Z | `ghcr.io/zaproxy/zaproxy:2.17.0@sha256:5ccfff9a...` の `zap-api-scan.py -t http://127.0.0.1:8000/openapi.json -f openapi -J`。API は `--network none` で起動したこのブランチのイメージ、ZAP は `--network container:api`（CD と同じ形） |

- `site` は 1 つ（`http://127.0.0.1:8000`）。警告は Low 3 つ・Informational 1 つで、High・Medium はない。
