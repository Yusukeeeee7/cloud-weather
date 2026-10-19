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

## 追加：1 mm 以上の雨の日数の、1 年あたりの合計（2026-10-19）

状態：承認済み（2026-10-19、人間の回答「全部おすすめで進めて」）

人間の要望（画面を見て）：「月ごとの 1 mm 以上の雨の日数」のグラフの下に、合計の日数を表示する。
人間の回答：このブランチ（`feature/issues_52-verify`、dev-log の PR）に足す／合計は「1 年あたりの日数」／計算は `ml/climate.py` で行う。

### 内容
- 合計 ＝ 月ごとの「年あたりの日数」（グラフの 12 本の棒。丸める前の値）を 12 か月ぶん足したもの。月によってデータのある年の数が違っても、グラフの棒の合計と一致する。
- いまの `climate.json` の値で足すと、東京 約 136.1 日、ベルリン 約 120.2 日（丸めた値の合計なので、作り直した値とは少し違うことがある）。
- `climate.json` に `cities.<city>.wet_days_1mm_per_year`（小数 1 桁。月が 1 つもなければ `null`）を足す。
- 画面：グラフの下に `<p id="wet-total" class="note">` を置き、「1 年あたりの合計：東京 136.1 日、ベルリン 120.2 日」と表示する（`textContent`）。値が `null` なら「—」。
- `09_climate.ipynb` を全期間（`DATA_FETCH_MODE=full`、`--network none`）で実行し直し、`climate.json` の差分がこのキーだけであることを `git diff` で確かめる。
- spec 5 の `climate.json` のキーの説明に、このキーを足す。

### 変更するファイル
| ファイル | 内容 |
|---|---|
| `ml/climate.py` | `yearly_wet_days`（都市ごとの合計）、`_city_summary` にキーを足す |
| `tests/ml/test_climate.py` | 下のテスト 1〜3 |
| `tests/app/test_ui_router.py` | 下のテスト 4・5 |
| `app/static/compare.html`・`compare.js` | 合計の表示 |
| `app/static/climate.json` | 全期間で作り直す |
| `docs/spec.md` | キーの説明 |

### テスト一覧（先に書く順）
| # | テスト名 | 種類 | 確かめること |
|---|---|---|---|
| 1 | `test_yearly_wet_days_sums_monthly_averages` | 正常 | 手で作った日のデータで、月ごとの年あたりの日数の合計になる（月によって年の数が違う場合を含む） |
| 2 | `test_yearly_wet_days_uses_threshold_boundary` | 境界 | 0.9 mm の日は数えず、1.0 mm の日は数える |
| 3 | `test_climate_summary_has_wet_days_per_year` | 正常 | `climate_summary` の都市ごとに、小数 1 桁のキーがある |
| 4 | `test_climate_json_full_*`（既存に足す） | 正常 | 全期間の JSON で 0〜366 日、月の値の合計と ±0.6 日以内で合う |
| 5 | `test_compare_has_wet_total` | 正常 | `compare.html` に `id="wet-total"` がある |

### 質問
1. 表示は小数 1 桁（例：136.1 日）でよいか。（おすすめ：小数 1 桁。グラフの月の値と同じ桁で、足し算が合っているかを見比べやすい）
2. 計画は以上でよいか。承認されたら Red から始めます。

## 追加 2：湿度・風・星空・アイス・ビール（2026-10-19）

状態：承認済み（2026-10-19、人間の回答「全部おすすめで進めて」。風向きのブロッカーは AI が照合する）

人間の要望（画面を見て）：アイス指数・ビール指数・星空指数、湿度の比較、風向き、風速（比較のグラフと「今日の天気」の両方）。
人間の回答：「全部このissuesでいい」（このブランチ・この PR に入れる）。CLAUDE.md の「1 つの PR で複数機能をまとめない」とは違うが、人間の判断として記録する。

### 手元のデータ（調べた結果）
- IEM の生データ（`data/raw/iem/*.csv`）には、すでに `relh`（相対湿度）・`drct`（風向）・`sknt`（風速）の列がある（fixture の見出しで確かめた）。取り直しは要らない。ただし、spec の IEM の行には載っておらず **未確認**。いまの `ml/metar.py` は読んでいない。
- 再解析の `relative_humidity`・`wind_speed_ms` は、確認済みで、`observations.parquet` にある。風向はない。
- 「今日の天気」：`current.wind_speed_ms` は、すでにタイルに出ている（`app.js` 134 行）。`hourly` には風速がない（Open-Meteo の `hourly=wind_speed_10m` は確認済み。#12 で予測用に取っている）。風向（`wind_direction_10m`）は **未確認**。

### 作るもの（案）と、進める順（おすすめ）
| 順 | もの | 画面 | データ | 状態 |
|---|---|---|---|---|
| 1 | 雨の日数の 1 年あたりの合計 | 比較 | 再解析 | 上の「追加」 |
| 2 | 湿度：月ごとの平均の露点（℃） | 比較（折れ線） | METAR の露点（確認済み） | すぐできる |
| 3 | 風速：月ごとの平均風速（m/s） | 比較（折れ線） | 再解析（確認済み） | すぐできる |
| 4 | 風速：1 時間ごとの風速 | 今日の天気 | `/weather` の `hourly` に `wind_speed_ms` を足す（spec の応答の変更） | すぐできる |
| 5 | 星空日和の夜の数（月ごと） | 比較（棒） | 雲量（再解析）、天文薄明（`app/services/solar.py`） | 決まりの承認が要る |
| 6 | アイス日和・ビール日和の日数（月ごと） | 比較（棒） | 日最高気温（METAR）、降水を観測したか | 決まりの承認と、気象庁の定義の確認が要る |
| 7 | 風向き（風配図）、今日の風向き | 比較（円）・今日の天気 | IEM の `drct`、Open-Meteo の `wind_direction_10m` | **ブロッカー** |

- それぞれ、`ml/climate.py`（または `app/`）のテストを先に書き、Red を見てから実装する。1 つずつコミットする。
- 星空・アイス・ビールは、画面に「このサイト独自の目安（日本気象協会などの指数とは別のもの）」と書く。

### 決まりの案（承認が要る）
- 星空日和の夜：その夜の天文薄明が終わってから始まるまで（太陽が −18° より下）の正時のうち、雲量（再解析）が 25 % 未満の時間が半分以上の夜。月の明るさ・街の明かりは入れない（データがない）。
- アイス日和：日最高気温（METAR、正時の値の最大）が 25 ℃以上で、降水を観測しなかった日。
- ビール日和：日最高気温が 30 ℃以上の日。
- 25 ℃・30 ℃は気象庁の「夏日」「真夏日」の基準のつもり。使う前に気象庁のページで定義を確かめる（人間の指示が要る）。正時の値の最大なので、本当の最高気温より低めになる（注に書く）。

### ブロッカー（人間の対応が必要なこと）
- 風向き：IEM の `drct`（度？）・`sknt`（ノット？）の意味と単位、風が弱く向きが定まらない（`VRB`）・無風（`00000KT`）のときの値を、公式ドキュメントと実データで確かめる。Open-Meteo の `wind_direction_10m` も同じ。これまでと同じく「人間の指示で AI が照合」する形でよいか。

### 質問
1. 湿度は、METAR の露点の平均でよいか。（おすすめ：露点。計算式が要らず、METAR を優先する方針に合う。相対湿度（%）にするなら、IEM の `relh` の確認か、計算式の確認が要る）
2. 進める順は上の表のとおりでよいか。（おすすめ：表のとおり。確認済みのデータで作れるものから）
3. 星空・アイス・ビールの決まりは、上の案でよいか。
4. ブロッカー（風向き）の確認を、AI に指示するか。
5. 雨の日数の合計は小数 1 桁でよいか（「追加」の質問 1）。

## 追加 3：読み込み中の表示（2026-10-19）

状態：承認済み（2026-10-19、人間の回答「全部おすすめで進めて」）

人間の報告：「東京を見てベルリンに移ると、たまに表示されない。読み込みのくるくるを置いてもいい」。

### 調べた結果（API のログ、2026-10-19 15:21Z ごろ）
- ベルリンの `/weather` で、Open-Meteo が 503・429 を返し、タイムアウトも続いた。再試行（2 回）のあと、`/weather?city=berlin` は 502（2 回とも）。東京は保存値があったので 200。
- 画面は、`/weather` の結果を待つあいだ、**前の都市（東京）の表示をそのまま残す**。読み込み中の印がないので、「表示されない」「東京のまま」に見える。502 のあとは「取得できませんでした」になる。
- ベルリンのボタンを押し直したり再読み込みしたりすると、そのたびに `/weather?city=berlin` が新しく始まり、保存値がないので、それぞれが Open-Meteo を呼んでいた（ログで、同じ時間に再試行が重なっている）。
- 429 の理由（Open-Meteo の上限を超えたのか、相手の混雑か）は分からない。こちらの呼び出しは、上限（600 回/分）よりずっと少ない。

### 内容（案）
- 都市を切り替えたら、すぐに各欄を「読み込み中」（くるくると「読み込み中…」の文字）にし、前の都市の値を消す。`aria-busy="true"` を付ける。
- 結果が来た欄から表示する（いまは全部そろってから表示）。→ 質問 2
- 動きを減らす設定（`prefers-reduced-motion`）では、くるくるを回さず文字だけにする。
- 取得できなかった欄に「もう一度読み込む」ボタンを置く。→ 質問 3

### 質問
1. 取りに行くのは、いまのとおり「画面を開いた・都市を押したとき」（保存値があればそれを返す）でよいか。（おすすめ：いまのまま。前もって定期的に取っておく形は、見る人がいなくても外部APIを呼び、仕組み（定期実行）も増える。今回の原因は Open-Meteo 側の失敗なので、前もって取っておいても同じように失敗する）
2. 欄ごとに、来たものから表示するか。（おすすめ：する。`/daylight` は外部APIを使わないので、すぐに出る）
3. 「もう一度読み込む」ボタンを置くか。（おすすめ：置く。押し直すと同じ都市の取得が重なるので、読み込み中は押せないようにする）
4. 同じ都市の取得が重なったとき、サーバーで 1 回にまとめる（2 つ目は 1 つ目の結果を待つ）か。（おすすめ：今回はしない。サーバーの変更で、テストも大きくなる。別の Issue で）

## 追加の進め方（2026-10-19、承認済み）

人間の回答「全部おすすめで進めて」で、追加・追加 2・追加 3 の質問はすべておすすめの案に決まった（雨の日数の合計は小数 1 桁、湿度は METAR の露点、決まりの案のとおり、風向きは AI が照合、取得は画面を開いたとき、欄ごとに表示、もう一度読み込むボタンを置く、サーバーでまとめるのは別の Issue）。
進める順：①読み込み中の表示 → ②雨の日数の合計 → ③露点 → ④月ごとの風速 → ⑤今日の天気の 1 時間ごとの風速 → ⑥星空 → ⑦アイス・ビール → ⑧風向き。

### 実装時の変更（①読み込み中の表示・②雨の日数の合計）
- ①：テストは、部品（「読み込み中…」・`aria-busy`・`role="status"`・「もう一度読み込む」・`.spinner` と動きを減らす設定）があるかだけを見る。JS を動かすテストの仕組みがないので、画面の動き（切り替えの直後に前の都市の値が消える、届いた欄から出る、同じ都市を押し直しても取得が重ならない）は人間がブラウザで確かめる。わざと壊す確認も、この動きには効かない。
- ①：日照の欄は、`/weather` と一緒に表示する（時刻を現地の時刻で出すのに `/weather` の `timezone` が要るため）。「届いた欄から表示」は、`/weather` のあとに呼ぶ 5 つ（雲底・過去 24 時間・雲底の予報・雲底の過去・日差し）に当てはまる。
- ①：`index.html` の `history-error`（`<p>`）を `history-status`（`<div>`）に替えた。読み込み中の表示と、「もう一度読み込む」ボタンを入れるため。
- ②：テスト 2 の境目は、既存のテストと同じく 0.99 mm と 1.0 mm にした（計画では 0.9 mm）。テスト 3 の前に、既存の `test_climate_summary_keys` の都市のキーの一覧に、新しいキーを足した（仕様の変更による）。
- ②：全期間で作り直した `climate.json` の差分は、新しいキーの 2 行だけ（東京 136.0 日、ベルリン 120.1 日。丸めた月の値の合計は 136.1・120.2 日）。
- わざと壊す確認（3 か所、すべて検出）：合計を平均にする、別の都市の値を使う、動きを減らす設定で `animation: none` を消す。

### 実装時の変更（③露点）
- 月ごとの平均を出す処理を `_monthly_mean` にまとめ、`monthly_temperature_c` と `monthly_dew_point_c` から使う。
- 比較ページでは、気温のグラフのすぐ下に置いた。
- 全期間で作り直した `climate.json` の差分は、`dew_point_c_metar` の 24 行だけ（東京 −2.2〜24.5 ℃、ベルリン −0.2〜12.8 ℃）。
- わざと壊す確認（4 か所）：別の列（気温）を使う・欠けた行を 0 にする・UTC の月で区切るは検出した。**値がすべて欠けた月を 0 ℃にする（`dropna` を消す）は、最初は検出しなかった**。`test_monthly_dew_point_drops_month_without_values` を足して検出するようにした（いまの動作を守るテストなので、Red にはならない）。

### 実装時の変更（④月ごとの風速）
- `_monthly_mean` を使う `monthly_wind_speed_ms` を足した。比較ページでは露点のグラフの下に置き、目盛りは 0 から始める。
- 全期間で作り直した `climate.json` の差分は、`wind_speed_ms_reanalysis` の 24 行だけ（東京 4.0〜5.2 m/s、ベルリン 2.9〜4.2 m/s）。
- 最初は画面の注と spec に「地上 10 m の風速」と書いたが、spec の表に高さの意味は確認済みとして書かれていない（項目の名前が `wind_speed_10m` なだけ）ので、項目の名前を書く形に直した。
- わざと壊す確認（2 か所、どちらも検出）：別の列（気温）を使う・別の月の表（露点）を引く。
- ⑤（今日の天気の 1 時間ごとの風速）：`/weather` のテストの fixture（2026-10-12 取得）に 1 時間ごとの風速がない。人間の回答「おすすめで」により、いまの取得と同じ URL で fixture を取り直してから進める。

### 実装時の変更（⑤今日の天気の 1 時間ごとの風速）
- `/weather` の fixture を、いまのアプリと同じ URL で取り直した（2026-10-19T18:25:57Z〜58Z、4 つとも 200。`tests/fixtures/README.md`）。`FIXED_NOW` を 2026-10-19T18:26:00.123456Z に変えた。古い fixture は `load_legacy_forecast`・`LEGACY_NOW` として、「4 項目のない保存値」のテストに残した。
- fixture を差し替えただけで 21 個のテストが失敗した。古い日時を直接書いていたもの（次の正時・現地の日付・`fetched_at`）を新しい時刻に読み替え、天気の分類のテストの期待値を新しい応答の天気コード（東京 2＝partly_cloudy、ベルリン 0＝clear。spec の表のとおり）に替え、応答の形のテストを、いまのアプリが頼む項目の一覧と比べる形にした。確かめる中身は変えていない。
- 「4 項目のない保存値」のテスト 4 つ（`/cloud-base` と `/cloud-base/forecast`、取り直すものと 502 のもの）は、準備で古い形の応答を `/weather` に通していた。いまの `/weather` は古い形を 502 にするので、`tests/conftest.py` の `seed_weather_cache` で保存先に直接入れる形に変えた（入ったことも確かめる）。そのため、取り直すテストの外部APIの呼び出し回数の期待値は 2 から 1 になった（準備の `/weather` の 1 回がなくなったため）。502 のテストは、準備が効かなくても 502 になって通ってしまっていたので、外部APIを呼んだことも確かめるようにした。
- わざと壊す確認（4 か所）：別の列（気温）を使う・null を受け付ける・文字を受け付けるは検出した。風速の列を「なくてもよい」にする壊し方は検出しなかったが、列の有無は `hourly_columns` が型の項目名から確かめているので、結果は同じ 502 になる（同じ動作になる壊し方）。

### 実装時の変更（⑥星空日和の夜）
- 人間の回答「実装へ進んで」で、Red のときに示した細かい決まりのとおりにした：暗くならない夜は数えない（0 夜）、夜は夕方の現地の日付の月に入れる（現地の正午から次の正午まで）、暗いかは `app/services/solar.py` の太陽の高度で正時ごとに決める、月の値は年あたりの夜の数。
- テストの期待値（暗い正時）は、fixtures の USNO の天文薄明の表（2026 年）から読んだ。境目から 2 分以内の正時は使わない（USNO は分単位で、±2 分ずれうる）。
- 全期間で作り直した `climate.json` の差分は、`star_nights` の 24 行と、その前の行の末尾の `,` だけ（値は変わっていない）。東京 5.6〜16.9 夜／月（年 117.7 夜）、ベルリン 0.0〜12.1 夜／月（6 月が 0.0、年 82.0 夜）。
- わざと壊す確認（6 か所）：暗い時間がない夜も数える・雲量の境目（`<`→`<=`）・昼の晴れも数える・夜を暦の日付で区切る・−12° にするは検出した。**「半分以上」を「半分より多い」にする壊し方は、最初は検出しなかった**。1 月の東京の夜は暗い正時が 11 個（奇数）で、「ちょうど半分」が作れなかったため。暗い正時が 8 個の 2026-04-15 の夜に替えて、検出するようにした。
