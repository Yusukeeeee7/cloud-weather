# 計画：#25 気候の比較ページ（Issue #52）

状態：承認済み（2026-10-19、人間の回答「おすすめで承認」。質問 1〜9 はすべておすすめのとおり。質問 4 は AI が WMO-No. 782 と照合する）

## 目的と受け入れ条件

spec.md にはまだない機能。Issue #52 と、2026-10-19 の人間の回答（「おすすめで進めて」「METAR を優先し、METAR にないものだけ再解析」）から、次の行を spec の「14. 機能一覧」に足す（この計画の承認で確定する）：

> | 25 | 気候の比較ページ | `data/processed/observations.parquet`（2018〜2025 年）から、東京とベルリンの気候の指標を集計して JSON に保存し、新しいページ `GET /compare` がそれを読んで棒・円・折れ線のグラフで比べる。値は METAR（実測）を優先し、METAR にないもの（降水量・空全体の雲量）だけ Open-Meteo の過去データ（再解析）を使い、グラフごとにどちらかを書く。集計は `ml/climate.py` の関数で行い、テストを付ける。日ごとの集計は現地の日付で区切る。ページは外部と通信せず、依存のパッケージを足さない（SVG を自分で描く） | 未着手 |

たとえ：工場の「年次報告書のグラフのページ」。毎日の検品の記録（`observations.parquet`）を経理が月ごと・年ごとに集計して 1 枚の表（`climate.json`）にし、掲示板（`/compare`）にグラフで貼る。記録には「検品係が自分で数えた数字（METAR、実測）」と「帳簿を付け直した数字（再解析）」があるので、グラフごとにどちらかの札を付ける。

| 決まり | たとえ | この機能でやること |
|---|---|---|
| 集計は `ml/` の関数 | 集計のやり方を手順書にして、誰がやっても同じ表になる | `ml/climate.py`（テスト付き）。ノートブック `09_climate.ipynb` はそれを呼んで JSON を保存するだけ |
| ページは JSON を読むだけ | 掲示板は表を貼るだけで、自分では計算しない | `GET /compare` は静的な HTML。JS が `/static/climate.json` を読んで SVG を描く |
| 実測と再解析の札 | 「自分で数えた」「付け直した」の札 | グラフの見出しの横に「実測（空港の METAR）」「再解析（Open-Meteo）」 |

## 調べたこと（2026-10-19）

- **データ**（spec 9「データ取得」の列の表）：METAR の列は `metar_temperature_c`・`metar_dew_point_c`・`visibility_m`・`sky_cover_1〜4`・`sky_height_1_m〜4_m`・`weather_codes`・`metar`。**METAR の列に降水量（mm）はない**。再解析の列は `temperature_c`・`precipitation_mm`（前の 1 時間の合計）・`cloud_cover`（%）など。
- **METAR の測り方の変化**（`observations.parquet` を `Dockerfile.dev` の中で集計。電文に `AUTO` を含む割合）：ベルリンは 2018〜2021 年 0.2〜0.4 %、2022 年 45.5 %、2023〜2025 年 100 %（自動観測に切り替わった）。東京は 8 年とも 0 %。東京の `CAVOK` の割合は 2018〜2022 年 6〜8 % から 2023〜2025 年 14〜16 % に増えた（理由は調べていない）。
- **METAR の欠け**：前後 30 分以内に METAR がない正時は、2 都市で 13 行（`docs/eda.md` 1 節）。
- **雲底**：`ml/target.py` の `target_m`（BKN・OVC・VV の最も低い高さと 1,524 の小さいほう。`CAVOK`・`NSC`・`NCD` は 1,524。高さのない層だけなら欠損）。spec 9 で WMO-No. 782 と照合済み。
- **天気の記号（`weather_codes`、IEM の `wxcodes`）**：列の名前は spec 7 の表で確認済み。**記号（`RA`・`DZ`・`SN`・`SH`・`VC`・`RE` など）の意味は、spec でまだ確かめていない**（ブロッカー）。
- **現地時刻**：`ml/features.py` の `_local_time`（`city` のタイムゾーンに直す。いまは時・月・年の何日目だけ）。日付・年が要るので、引数を足すか、`ml/climate.py` に同じ考えの関数を作る（実装のときに、既存のテストを壊さないほうを選ぶ）。
- **画面**：`app/routers/ui.py` は `GET /`（`include_in_schema=False`）で `index.html` を返すだけ。JS は `app/static/app.js`（`createElementNS` で SVG を描く。`innerHTML` を使わない）。`tests/app/test_ui_router.py` が、静的ファイルの配り方・外部ホストを読まないこと・`innerHTML` を使わないことを確かめている。
- **イメージ**：`Dockerfile` は `app`・`ml`・`models` を入れる（`data`・`notebooks`・`reports` は入らない）。`app/static/climate.json` に置けば、イメージに入り、いまの `/static` の仕組みで配れる。
- **DAST**：`/compare` は `include_in_schema=False` にするので、`/openapi.json` の道の数（8）は変わらない（CD の「取り込んだ URL が 8 未満なら失敗」に影響しない）。

## 内容

### 1. 集計 `ml/climate.py`

入力は `observations.parquet` の表（都市 × 正時、UTC）。期間は **現地の日付で 2018-01-01〜2025-12-31**。

| 関数（案） | 何をするか |
|---|---|
| `local_date(observations)` | `time`（UTC）を `city` のタイムゾーンの日付にする |
| `complete_days(observations)` | その現地の日の行がそろっている日だけを残す（夏時間の切り替え日は 23・25 行。足りない日は捨てる）。データの端（東京・ベルリンの 2018-01-01、東京の 2026-01-01）は欠けるので捨てる |
| `monthly_temperature_c(observations, source)` | 月（1〜12）ごとの平均気温。`source` は `"metar"`（`metar_temperature_c`）か `"reanalysis"`（`temperature_c`）。欠損の行は除く。8 年分をまとめた平均 |
| `daily_precipitation_mm(observations)` | 現地の日ごとの降水量の合計（再解析）。そろった日だけ |
| `yearly_precipitation_mm(observations)` | 年ごとの合計（そろった日の合計。2018 年は 1 月 1 日が欠ける） |
| `monthly_wet_days(observations, threshold_mm=1.0)` | 月ごとの「1 mm 以上の日」の数の、年あたりの平均（再解析）。`>= 1.0` を数える |
| `monthly_precipitation_observed_days(observations)` | 月ごとの「METAR で降水を観測した日」の数の、年あたりの平均（**ブロッカー**：記号の意味の確認が要る。質問 4） |
| `cloud_cover_share(observations)` | 雲量（再解析、%）の 4 つの区分の割合：`0〜25 未満`・`25〜50 未満`・`50〜75 未満`・`75〜100`（質問 3） |
| `monthly_low_ceiling_share(observations)` | 月ごとの「シーリングが 1,524 m より下にある時間」の割合（METAR。`target_m < 1524`。`target_m` が欠損の行は分母から除く） |
| `yearly_metar_auto_share(observations)` | 年ごとの「電文に `AUTO` がある時間」の割合（ページに測り方の変化を出すため） |
| `climate_summary(observations)` | 上をまとめて、下の JSON の形の辞書を返す |

### 2. 成果物 `app/static/climate.json`

ノートブック `09_climate.ipynb` が `climate_summary` の結果を保存する（`full` のときだけ。既定の `sample` では一時的な場所に書く。ほかのノートブックと同じ）。キー：

```json
{
  "source": "data/processed/observations.parquet",
  "period": {"start": "2018-01-01", "end": "2025-12-31", "dates": "local"},
  "cities": {
    "tokyo": {
      "monthly": [
        {
          "month": 1,
          "temperature_c_metar": 0.0,
          "temperature_c_reanalysis": 0.0,
          "wet_days_1mm": 0.0,
          "precipitation_observed_days": 0.0,
          "low_ceiling_share": 0.0
        }
      ],
      "yearly": [
        {"year": 2018, "precipitation_mm": 0.0, "complete_days": 364, "metar_auto_share": 0.0}
      ],
      "cloud_cover_share": {"0-25": 0.0, "25-50": 0.0, "50-75": 0.0, "75-100": 0.0}
    },
    "berlin": {}
  }
}
```

- `monthly` は 12 行（1〜12 月）、`yearly` は 8 行（2018〜2025）。割合は 0〜1、小数 3 桁。気温・日数・降水量は小数 1 桁。
- 値に NaN・無限大を入れない（`json.dumps(..., allow_nan=False)`）。

### 3. 画面 `GET /compare`

- `app/routers/ui.py` に `GET /compare`（`include_in_schema=False`）。`app/static/compare.html` を返す。JS は `app/static/compare.js`、CSS はいまの `style.css` を使う（足りない分を足す）。
- `compare.js` は `/static/climate.json` を読み、`createElementNS` で SVG を描く。値は `textContent` で入れる（`innerHTML` を使わない）。外部のホストを読まない。
- グラフ（どれも東京とベルリンを並べる）：

| # | グラフ | 形 | 値の出どころ |
|---|---|---|---|
| 1 | 月ごとの平均気温 | 折れ線（実測は実線、再解析は破線。ずれが見える） | 実測（METAR）と再解析 |
| 2 | 年ごとの降水量 | 棒 | 再解析 |
| 3 | 月ごとの 1 mm 以上の日数 | 棒 | 再解析 |
| 4 | 月ごとの降水を観測した日数 | 棒 | 実測（METAR）。**ブロッカーが解けなければ外す**（質問 4） |
| 5 | 雲量の分布 | 円（都市ごとに 1 つ） | 再解析 |
| 6 | 月ごとの低いシーリングの時間の割合 | 折れ線 | 実測（METAR） |

- 注：「再解析は、観測を入れて数値モデルで計算し直した値（数十 km のマス目の平均）で、気象庁などの観測の統計とは違うことがある」「ベルリンの METAR は 2022 年に自動観測に切り替わった（年ごとの `AUTO` の割合）」「2018 年の降水量は 1 月 1 日を含まない」。出典（Open-Meteo の CC BY 4.0、IEM）を書く。
- `index.html` に `/compare` へのリンク、`compare.html` に `/` へのリンク。

### 4. spec の更新

- 「5. API仕様」に `GET /compare`（画面）の節。
- 「9.」のノートブックの表に `09_climate.ipynb` の行。
- 「14. 機能一覧」に #25 の行（上の案）。

## 今回やらないこと

- 湿度のグラフ（METAR に湿度の列はなく、気温と露点から計算する式が要る。式を spec で確かめていないので入れない）。
- 視程のグラフ（候補にしたが、グラフを 6 つに絞った。要望があれば別の Issue）。
- 新しい API（`/climate` など）。ページは静的な JSON を読むだけ。
- 外部 API の新しい取得（すでにある `observations.parquet` だけを使う）。
- 気象庁などの平年値との比較。
- ベルリンの自動観測への切り替えが雲底の予測モデルに与える影響の調査（別の Issue の候補）。

## 変更・追加するファイル
| ファイル | 内容 |
|---|---|
| `ml/climate.py` | 新規。集計の関数 |
| `tests/ml/test_climate.py` | 新規。集計の関数のテスト（小さな表を手で作る） |
| `notebooks/09_climate.ipynb` | 新規。`climate_summary` を呼び、`app/static/climate.json` を保存する（出力は消してコミット） |
| `app/static/climate.json` | 新規。成果物（全期間で実行したもの） |
| `app/static/compare.html`・`compare.js` | 新規。比較のページ |
| `app/static/style.css`・`index.html` | グラフの見た目、`/compare` へのリンク |
| `app/routers/ui.py` | `GET /compare` |
| `tests/app/test_ui_router.py` | `/compare` と新しい静的ファイルのテスト |
| `tests/test_notebooks.py` | 必要なら 09 の確認（02〜08 と同じ形） |
| `docs/spec.md` | 5・9・14 節 |
| `docs/plans/25-climate-compare.md` | この計画 |

## テスト一覧（先に書く順）
| # | テスト名 | 種類 | 確かめること |
|---|---|---|---|
| 1 | `test_local_date_uses_city_timezone` | 正常 | 東京は UTC 15:00 で日付が変わる、ベルリンは冬 23:00・夏 22:00 で変わる |
| 2 | `test_complete_days_drops_partial_days` | 境界 | 23 行の普通の日は捨て、24 行の日は残す |
| 3 | `test_complete_days_dst_days` | 境界 | ベルリンの夏時間の切り替え日（3 月は 23 行、10 月は 25 行）がそろった日として残る |
| 4 | `test_monthly_temperature_metar_and_reanalysis` | 正常 | `source` ごとに正しい列の平均。欠損の行は除く |
| 5 | `test_monthly_temperature_rejects_unknown_source` | 異常 | `source` が 2 つ以外なら `ValueError` |
| 6 | `test_daily_precipitation_sums_local_day` | 正常 | 現地の日ごとの合計（UTC の日付ではない） |
| 7 | `test_wet_days_threshold_is_inclusive` | 境界 | 0.99 mm は数えず、1.0 mm は数える |
| 8 | `test_wet_days_average_per_year` | 正常 | 2 年分で、月ごとの日数が年あたりの平均になる |
| 9 | `test_yearly_precipitation_counts_complete_days` | 正常 | 年の合計と `complete_days` の数 |
| 10 | `test_cloud_cover_share_bands` | 境界 | 24.9・25・49.9・50・74.9・75・100 がそれぞれの区分に入る。割合の合計が 1 |
| 11 | `test_cloud_cover_share_rejects_out_of_range` | 異常 | 0 未満・100 超・NaN があれば `ValueError`（黙って捨てない） |
| 12 | `test_low_ceiling_share_excludes_unknown` | 正常 | `target_m` が欠損の行は分母に入らない。`< 1524` だけを数える |
| 13 | `test_low_ceiling_share_cap_is_not_low` | 境界 | ちょうど 1,524（`CAVOK` など）は「低い」に入らない |
| 14 | `test_metar_auto_share` | 正常 | 電文に `AUTO` を単語として含む行の割合（`AUTOMATIC` のような別の語は数えない） |
| 15 | `test_precipitation_observed_days`（ブロッカーが解けたら） | 正常・境界 | 確かめた記号だけを数える。`RE`（直前の天気）・`VC`（近く）は数えるかを質問 4 の結果で決める |
| 16 | `test_climate_summary_keys` | 正常 | JSON のキー・12 か月・8 年・2 都市 |
| 17 | `test_climate_summary_has_no_nan` | 異常 | 値に NaN・無限大がない（`allow_nan=False` で書ける） |
| 18 | `test_compare_returns_html` | 正常 | `GET /compare` が 200・HTML、`/static/compare.js` を読む |
| 19 | `test_compare_not_in_openapi` | 正常 | `/openapi.json` に `/compare` がない（DAST の道の数が変わらない）。**Red にならないかもしれない**（`include_in_schema=False` を書けば最初から通る。守るためのテスト） |
| 20 | `test_static_files_served`（`compare.js`・`climate.json` を足す） | 正常 | ファイルのまま返る |
| 21 | `test_static_has_no_external_hosts`（新しいファイルを足す） | 正常 | 外部のホストを読まない |
| 22 | `test_compare_script_does_not_use_inner_html` | 正常 | `compare.js` に `innerHTML` などがない。**Red にならない**（ファイルがないと失敗する形で Red にする） |
| 23 | `test_climate_json_matches_schema` | 正常 | コミットした `app/static/climate.json` のキー・行数・値の範囲（割合 0〜1、日数 0〜31） |
| 24 | nbmake で `09_climate.ipynb` | 正常 | サンプルデータで上から実行できる |

- 期待値は、テストの中の小さな表から手で数えられる値にする（外部の計算結果を要する値はない）。
- ページの見た目（グラフの形）は自動のテストにしない。人間がブラウザで見て確かめる（#15 と同じ）。

## 追加する依存パッケージ
なし（pandas は依存グループ `ml` にある。ページは素の JS と SVG）。

## セキュリティ上の注意
- 入力検証：`/compare` は引数を取らない。JSON は自分で作った静的なファイル。JS は値を `textContent` と SVG の属性（数値）で入れる。
- シークレット：使わない。JSON にはパス（`source`）と集計値だけで、個人の環境のパスを入れない（テストで確かめる）。
- 外部通信（ホスト・タイムアウト）：なし。集計は手元のファイルだけ、ページは同じオリジンの `/static/climate.json` だけを読む。

## リスク・未決事項
- `climate.json` は、全期間のデータ（git 管理外）で作ったものをコミットする。CI では作り直せない（ノートブックはサンプルで動くことだけ確かめる）。作り直すときは人間が `full` で実行する。
- `observations.parquet` は、作り直すと値が変わることがある（再解析の更新）。JSON に作った日を入れるかは質問 7。
- 月ごとの平均は、8 年のすべての時間を同じ重さで平均する（年ごとに平均してから平均するのではない）。欠けた時間が少ない（13 行）ので差は小さい。
- 雲量の区分（25 % ごと）は、METAR の FEW・SCT・BKN・OVC の区分とは一致しない。
- 画面は見ながら要望が増えやすい。追加の要望は、その都度「この Issue に足すか、別の Issue にするか」を聞く。

## ブロッカー（人間の対応が必要なこと）
- **METAR の天気の記号の意味**（`weather_codes`）が spec で未確認。グラフ 4（降水を観測した日数）に要る。どの記号を「降水」と数えるか（`DZ`・`RA`・`SN`・`SG`・`PL`・`GR`・`GS`・`UP`、強さの `-`・`+`、`SH`・`TS`・`FZ` の付いたもの、`VC`（近く）・`RE`（直前）を数えるか）を、公式の資料（WMO-No. 782 の METAR の天気の節。#10 で照合に使った資料）で確かめる必要がある（質問 4）。

## 質問
1. **JSON の置き場所を `app/static/climate.json` にしてよいか。**（おすすめ：する。イメージに入り、いまの `/static` で配れる。`reports/` に置くと `Dockerfile` の変更か新しい API が要る）
2. **ページの URL を `GET /compare` にしてよいか。**（おすすめ：`/compare`。画面と同じく `include_in_schema=False` で、DAST の道の数は変わらない）
3. **雲量の円グラフの区分を、25 % ごとの 4 つにしてよいか。**（おすすめ：25 % ごと。単純で、境目のテストが書きやすい。METAR の FEW・SCT・BKN・OVC には合わせない）
4. **ブロッカー：METAR の天気の記号の確認をどうするか。**（おすすめ：人間の指示で、AI が WMO-No. 782 の天気の節を照合し、spec の表に「確認済み」として書く（#8・#10 と同じやり方）。確かめられなければグラフ 4 を外して進める）
5. **「低いシーリング」を `1,524 m より下` にしてよいか。**（おすすめ：する。予測モデルの上限（`target_m`）と同じで、`CAVOK`・`NSC` の基準とも合う）
6. **2018 年の降水量が 1 月 1 日を含まない（現地の日付で区切るため）のを、注に書いて進めてよいか。**（おすすめ：注に書く。UTC で区切ると CLAUDE.md の決まり「日単位のデータは現地の日付で区切る」に反する）
7. **JSON に作った日時を入れるか。**（おすすめ：入れない。入れると、作り直すたびに中身が変わり、同じ結果かを比べにくい。作り直した記録は dev-log に書く）
8. **集計はノートブック `09_climate.ipynb` で行い、`ml/climate.py` を呼ぶ形でよいか。**（おすすめ：ノートブック。CLAUDE.md「成果物はノートブックで、処理は `ml/`」の決まりと同じ）
9. **湿度・視程はグラフにしない、でよいか。**（おすすめ：しない。湿度は計算式の確認が要る。視程は、要望があれば別の Issue）

## 実装時の変更

- **ブロッカー（質問 4）を解いた**（2026-10-19）。WMO の e-Library（`library.wmo.int`）にはこの環境から接続できなかった（curl の結果 000）。そこで、モンゴルの航空気象の機関（`amc2.namem.gov.mn`）が公開している WMO-No. 782 の 2025 年版の PDF を取得した。表紙で 2025 edition・ISBN 978-92-63-10782-4 を確かめ、5 節「PRESENT WEATHER」（Code table 4678）・補足の「Recent weather」・天気の説明（23 `DR`・24 `BL`）の原文を `pdftotext` で読んだ。WMO の公式のサイトから取ったものではなく、規定そのもの（WMO-No. 306）も読んでいない。結果は spec 7 の表に「METAR の天気の記号」として書いた。
- 降水を数える決まり（`is_precipitation`）：群を空白で分け、強さ（`-`・`+`）を取って 2 文字ずつに分ける。`DZ`・`RA`・`SN`・`SG`・`PL`・`GR`・`GS`・`UP` のどれかを含み、`VC`（近く）で始まらず、`DR`・`BL`（吹き上げられた雪など。降水ではない）を含まない群があれば降水とする。`TS` だけ・`VCSH` は数えない。
- データの `weather_codes` には、直前の天気（`RE`）が入っていないことを確かめた（電文に `RERA` などがある 1,167 行で、`weather_codes` に `RE` はない）。なので、`RE` を数えるかの判断は要らなかった。
- 「降水を観測した日」は、その現地の日の正時の METAR（前後 30 分以内の 1 つ）のどれかで降水があった日。正時のあいだだけ降った日は数えられないので、実際の日数より少なめになる（ページの注に書く）。
- JSON に `mode`（`full`／`sample`）のキーを足した。`reports/*.json` と同じく、全期間で作ったものかをテストで確かめるため。
- テストの名前・数が計画の一覧から少し変わった：足したもの（`test_local_date_requires_utc`、`test_monthly_temperature_uses_local_month`、`test_daily_precipitation_drops_day_with_missing_value`、`test_climate_summary_keeps_only_given_years`、`test_climate_summary_rejects_unknown_mode`、`test_climate_summary_rounds_values`、`test_root_links_to_compare`、`test_compare_script_reads_only_climate_json`、`test_climate_json_has_no_local_paths`、`test_climate_notebook_exists`）。計画の 22（`innerHTML`）は、既存のテストを `app.js`・`compare.js` の 2 つで動かす形にした。
- 全期間で `09_climate.ipynb` を実行した（2026-10-19、人間の回答「おすすめで実行して」。`Dockerfile.dev` の中で `--network none`、`DATA_FETCH_MODE=full`。nbconvert がイメージにないので `pytest --nbmake` で実行し、ノートブックのファイルは書き換えていない）。`app/static/climate.json` は 8.7 KB。
- わざと壊す確認（14 か所）：12 か所は検出した。最初に「欠けた行を分母に入れる」を検出しなかったのは、壊し方の誤り（後の行の絞り込みで同じ結果になった）で、`known` をすべて真にする壊し方では検出した。**検出しなかった 2 か所**（人間に報告）：
  - `VC` で始まる群を除く条件を消しても、テストが通る。WMO の表で `VC` と組み合わせるのは `SH`・`TS`・`FG`・`PO` などで、降水の記号（`RA` など）とは組み合わせないので、いまのテストの群（`VCSH`・`VCTS`）では、条件があってもなくても結果が同じ。
  - `climate_summary` の期間の絞り込みを消しても、テストが通る。期間の外の行の値が、期間の中と同じ（気温 10.0 など）だったため。
- レビューの指摘で直した（2026-10-19、人間の回答「おすすめで直して」）：
  - 画面の気温のグラフの注に、調べていないずれの原因を言い切って書いていた。「理由は調べていない」に直した。
  - 「数十 km のマス目」の数字に根拠がなかった（spec 7 の表は「ERA5 など」だけ）。画面と spec から数字を消した。
  - テストのなかった 2 つの分かれ道（2 文字ずつに分けられない群、`years` が空）にテストを足した。いまの動作を守るテストなので、Red にはならない。
  - 使っていなかった `TemperatureSource` を `monthly_temperature_c` の引数の型にした。`_rounded` の `type: ignore` 2 つを、`numbers.Real` で確かめる形にして消した。全期間でもう一度集計し、`climate.json` が変わらないこと（`git diff` で差分 0 行）を確かめた。
