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

## 2 種類ある理由

- `forecast_<city>.json`：アプリが実際に受け取る形（時刻が UNIX 秒）。
- `forecast_<city>_iso8601.json`：同じ時刻に、時刻形式だけ変えて取得したもの。`daily.time` に
  Open-Meteo が区切った **現地の日付** が文字列で入っているので、日付の期待値として使う。
  時刻以外の値は 2 つのファイルで一致している。

## 取得した時刻について

- 東京は、**現地の日付（10-13）が UTC の日付（10-12）より進んでいる時刻** に取得している。
  「日付を UTC ではなく現地で区切る」ことを確かめるため。
- ベルリンは同じ時刻（現地 17:02）で、現地と UTC の日付は同じ（10-12）。
- `hourly` の 24 件は時計に依存するため、`tests/conftest.py` の `FIXED_NOW` を取得時刻に合わせている。
  fixture を取り直したら `FIXED_NOW` も変える。

出典：[Weather data by Open-Meteo.com](https://open-meteo.com/)（CC BY 4.0）
