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
