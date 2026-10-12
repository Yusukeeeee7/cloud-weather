# tests/fixtures

外部APIの実際の応答を保存したもの。テストの期待値はここから読む（AIが値を作らない）。
応答は加工せず、取得したままの内容で保存している。

| ファイル | 取得日時（UTC） | 取得方法 |
|---|---|---|
| `open_meteo/forecast_current_tokyo.json` | 2026-10-12T13:41:02Z | `curl`、下の URL（`latitude=35.55&longitude=139.78`） |
| `open_meteo/forecast_current_berlin.json` | 2026-10-12T13:41:02Z | `curl`、下の URL（`latitude=52.36&longitude=13.50`） |

```
https://api.open-meteo.com/v1/forecast?latitude=<緯度>&longitude=<経度>&current=temperature_2m,apparent_temperature,dew_point_2m,relative_humidity_2m,precipitation,weather_code,cloud_cover,cloud_cover_low,cloud_cover_mid,cloud_cover_high,wind_speed_10m&wind_speed_unit=ms
```

出典：[Weather data by Open-Meteo.com](https://open-meteo.com/)（CC BY 4.0）
