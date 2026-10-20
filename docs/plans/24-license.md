# 計画：#24 Scorecard の残り ライセンスを決める（Issue #56）

状態：保留（2026-10-20、持ち主の判断「いまはやらないでいいや」。再開するときは質問 1 から決める）

## 目的と受け入れ条件

Issue #56 の本文（引用）：

> Scorecard の License が 0 点（#24、`docs/scorecard.md`）。付けるか、どのライセンスにするかは持ち主（人間）が決める。決まったら LICENSE を置く。なお、学習データの Open-Meteo は CC BY 4.0（`docs/model-card.md`）。

`docs/scorecard.md`「点の低い項目への対応」の License の行（引用）：

> | License | 0 | 人間が決める（別の Issue） | 付けるか、どのライセンスにするかは持ち主が決めること |

spec 14 章には、この作業の行がない。#55 と同じく、Scorecard（#24）の「点の低い項目」の 1 つとして扱う（質問 4）。

この Issue での受け入れ条件（上から。質問 1 で「付ける」を選んだ場合）：

1. 持ち主が、付けるライセンスを決める（質問 1）。
2. リポジトリの直下に `LICENSE` があり、中身は選んだライセンスの本文だけ（年と著作権者の名前を入れる）。
3. GitHub がライセンスを認識している（`GET repos/.../license` の `license.spdx_id` が選んだもの）。
4. 第三者のデータ（Open-Meteo・IEM・NOAA など）は、コードのライセンスと別であることと、その出典・条件を書く（質問 3）。
5. マージ後の Scorecard の License の点を `docs/scorecard.md` に記録する。

たとえ：工場で作った道具に「この道具はこの条件で使ってよい」という札を付ける。札がないと、店先に並んでいても（public でも）、法律上は誰も持ち帰って使えない。ただし、道具の中に入っている他社の部品（天気のデータ）には、他社の札（CC BY 4.0 など）が付いたままになる。

## 調べたこと（2026-10-20、AI が `gh api` で確認）

**リポジトリの状態**

| 項目 | 結果 |
|---|---|
| `LICENSE`・`COPYING` など | なし |
| `GET repos/Yusukeeeee7/cloud-weather/license` | 404 |
| `GET repos/Yusukeeeee7/cloud-weather` の `license` | `null`（`visibility` は `public`） |
| `pyproject.toml` の `license` | なし |

**Scorecard の License の採点**（`ossf/scorecard` の v5.6.0 の `docs/checks.md` と `checks/evaluation/license.go` を `gh api` で取得して読んだ）：

| 条件 | 点（ソース） | 点（`checks.md`） |
|---|---|---|
| ライセンスのファイルがある（`hasLicenseFile`） | 9 | 6（ファイルがある）＋ 3（直下にある） |
| FSF か OSI が認めたライセンス（`hasFSFOrOSIApprovedLicense`） | 1 | 1 |

- GitHub のリポジトリでは、GitHub の License API の結果を使う（`checks.md`）。つまり **GitHub が本文から種類を見分けられないと、FSF・OSI の 1 点が入らない見込み**。`LICENSE` には本文だけを書き、データの説明などを混ぜない（質問 3）。
- MIT・Apache-2.0 なら見込みは 10 点。実際の点はマージ後の実行で確かめる（AI が点を予想で書かない）。

**ライセンスの本文**：AI が記憶で書かず、`gh api licenses/<key>` の `body` を使い、`[year]`・`[fullname]` だけを置き換える（`implementation` の指示：「Replace [year] with the current year and [fullname] with the name (or names) of the copyright holders.」）。

**第三者のデータでリポジトリに入っているもの**（`git ls-files`）：

| ファイル | 出どころ | 条件（spec 7 章・`tests/fixtures/README.md` に書いてあるもの） |
|---|---|---|
| `tests/fixtures/open_meteo/*`・`tests/fixtures/data_raw/open_meteo_archive/*` | Open-Meteo の応答そのもの | CC BY 4.0（出典の表示が要る） |
| `tests/fixtures/data_raw/iem/*` | IEM（METAR） | パブリックドメイン（IEM の名前を書くことが望ましい） |
| `tests/fixtures/noaa/solar_calculations_day.json` | NOAA のスプレッドシートの値 | spec・README に条件の記載なし（出典の名前とリンクだけある。リスク参照） |
| `models/*.joblib`・`reports/*.json`・`app/static/climate.json` | 上のデータから学習・集計したもの | Open-Meteo の CC BY 4.0 の出典の表示が要る（`docs/model-card.md`） |

- Open-Meteo の「無料の API は非商用のみ」は、API を呼ぶときの利用の条件で、コードのライセンスとは別。MIT などで商用の利用を許しても、このコードで無料の API を商用に呼んでよいことにはならない。これも別のファイルに書く（質問 3）。

## 選択肢（質問 1）

| 案 | 中身 | Scorecard の見込み | よいところ | 気をつけること |
|---|---|---|---|---|
| **MIT**（おすすめ） | 著作権の表示を残せば、商用も含めて自由に使ってよい。保証なし | 10 | 短い（約 20 行）。学習用・ポートフォリオで最も多い。GitHub が確実に見分けられる | 特許の扱いは書かれていない（個人の学習用なので問題になりにくい） |
| Apache-2.0 | MIT ＋ 特許の許諾、変更したら書くこと | 10 | 特許の扱いがはっきりしている | 本文が長い（約 200 行）。会社のプロジェクト向き |
| GPL-3.0 | 改変して配ったら、同じ GPL で中身を公開すること | 10 | 改変版も公開させられる | 使う側の条件が重い。依存（FastAPI など）は MIT・BSD 系なので、混ぜても問題はないが、学習用には重い |
| 付けない | すべての権利を持ち主が持つ（見るのはよいが、写して使うことは許していない） | 0 のまま | 何も変えない | Scorecard は 0 のまま。`docs/scorecard.md` の対応を「直さない」にして理由を書く |

- 一度 MIT などで公開すると、その版を受け取った人の権利は取り消せない（あとで変えても、変える前の版は前のライセンスのまま）。持ち主が決めることなので、AI はおすすめだけを示す。

## 進め方（順番）

1. ブランチ `feature/issues_56` で、計画・`LICENSE`・`NOTICE.md`（質問 3）・spec の 1 行をコミットして PR を出す。
2. 人間がマージする。
3. マージ後、AI が `gh api repos/.../license` で GitHub の認識を確かめる（既定のブランチに入ってから認識されるため）。Scorecard の点を記録する別の PR（`feature/issues_56-verify`）を出す。**`Closes #56` はこの最後の PR に付ける**（質問 6）。

人間に設定画面の操作を頼むことはない。

## 今回やらないこと

- `pyproject.toml` に `license` を足すこと（質問 5）。
- ソースのファイルごとの見出し（SPDX の 1 行のコメント）。
- README の作成。
- 過去のコミットの書き換え（履歴は変えない）。
- アプリのコード・テスト・ワークフロー・画面の出典の表示の変更（画面の出典は #15・#25 で表示済み）。

## 変更・追加するファイル

| ファイル | 内容 |
|---|---|
| `LICENSE` | 新規（リポジトリの直下）。選んだライセンスの本文だけ（`gh api licenses/<key>` の `body`、年は 2026、著作権者は質問 2） |
| `NOTICE.md` | 新規（リポジトリの直下）。下の「NOTICE.md の中身（案）」（質問 3） |
| `docs/plans/24-license.md` | この計画 |
| `docs/spec.md` | 10 章（非機能要件）に「ライセンス：コードは MIT（`LICENSE`）。第三者のデータの出典と条件は `NOTICE.md`」の 1 行。14 章には行を足さない（質問 4） |
| `docs/scorecard.md` | 別の PR（手順 3）：License の行の対応と、設定後の点（`api.scorecard.dev` の JSON から写す） |
| `docs/dev-log.md`・`.claude/skills/*` | いまの作業ツリーにある #55 の dev-log と skill の変更を、このブランチで別のコミットにする（決まりどおり。PR の本文にも書く） |

テストへの影響：`LICENSE`・`NOTICE` を参照するテスト・コードはない見込み（実装時に `tests/`・`app/`・`ml/`・`scripts/` を `grep` で確かめる）。`Dockerfile` と `.dockerignore` に影響がないか（`COPY . .` などでイメージに入るか）も実装時に見る。

## NOTICE.md の中身（案）

日本語を先に、短い英語を後に置く（`SECURITY.md` と同じ）。

1. **コード**：このリポジトリのコードは `LICENSE`（MIT）。
2. **第三者のデータ**：コードのライセンスは、次のデータには当てはまらない。それぞれの提供元の条件に従う。
   - Open-Meteo（`tests/fixtures/open_meteo/` など、と、それから作った `models/`・`reports/`・`app/static/climate.json`）：Weather data by Open-Meteo.com、CC BY 4.0、リンク。
   - Iowa Environmental Mesonet（METAR）：出典の名前とリンク。
   - NOAA Global Monitoring Laboratory の Solar Calculator：出典の名前とリンク（条件は書かない。リスク参照）。
3. **API の利用の条件**：Open-Meteo の無料の API は非商用のみ。このコードを商用に使うときは、Open-Meteo の条件を確かめること。
4. **English**：1〜3 を短く。

- 条件は spec 7 章の「確認済み」の内容だけを書く。法律の解釈（「派生物は〜になる」など）は書かない。

## テスト一覧（確かめる順）

文書と GitHub の認識だけなので、pytest のテストではなく、確かめのシナリオにする。TDD の「Red」にあたるのはシナリオ 0。

| # | シナリオ | 種類 | 確かめること |
|---|---|---|---|
| 0 | 変える前に `GET repos/.../license` | 異常（Red） | 404（調べたことの表と同じ。記録する） |
| 1 | `LICENSE` を `gh api licenses/<key>` の `body` と比べる（作業用のスクリプト。リポジトリには入れない） | 正常 | `[year]`・`[fullname]` を置き換えた所のほかは 1 文字も違わない。余計な文章がない |
| 2 | `NOTICE.md` を読み、spec 7 章の条件と比べる | 正常 | 書いた条件が spec の「確認済み」の内容と一致する。シークレット・メールアドレスがない（gitleaks も CI で見る） |
| 3 | マージ後、`GET repos/.../license` | 正常 | `license.spdx_id` が選んだもの（MIT なら `MIT`）、`path` が `LICENSE` |
| 4 | マージ後の Scorecard の実行 | 結果で中身が変わる（Red にならない） | License が 0 より上になる。点・理由・details を `api.scorecard.dev` の JSON から写して記録する。見込み（10）と違ったら、理由を出力から読んで書く |
| 5 | 既存の全テスト・ruff・mypy（PR の CI） | 正常（Red にならない。いまの動作を守る） | コードを変えていないので、すべて通る |

## 追加する依存パッケージ

なし

## セキュリティ上の注意

- 入力検証：該当なし（アプリのコードは変えない）。
- シークレット：使わない。著作権者の名前に本名・メールアドレスを書くかは持ち主が決める（質問 2）。
- 外部通信：`api.github.com`（`gh api` の GET だけ）、`api.scorecard.dev`（結果の JSON を読む）。アプリの通信先は変わらない。

## リスク・未決事項

- **ライセンスは取り消せない**：一度公開した版の条件は、あとで変えても残る（選択肢の表の下）。
- **GitHub が見分けられない**と、FSF・OSI の 1 点が入らない。`LICENSE` には本文だけを書き、シナリオ 1・3 で確かめる。
- **NOAA の値の条件は spec にない**：アメリカの政府の機関の著作物はパブリックドメインのことが多いが、確かめていないので書かない（推測で書かない）。条件まで書くなら、人間に公式のページでの確認をお願いする（質問 3）。
- `docs/checks.md` は「6 ＋ 3 ＋ 1」、v5.6.0 のソースは「9 ＋ 1」と書き方が違う。合計はどちらも 10 で、結果を記録するときにソースの書き方で説明する。
- AI は法律の専門家ではない。この計画は、ライセンスの種類と、spec に確認済みの条件を整理するだけ。

## ブロッカー（人間の対応が必要なこと）

- **ライセンスを付けるか、どれにするかの決定**（質問 1）。決まるまで実装しない。
- 著作権者の名前（質問 2）。
- この PR と `-verify` の PR のマージ。
- spec 7 章の外部 API の項目は使わない。ブロッカーなし。

## 質問

1. **ライセンスを付けるか、どれにするか。**（おすすめ：**MIT**。短く、学習用・ポートフォリオで最も多く、GitHub が確実に見分けられて Scorecard も 10 点の見込み。特許の扱いをはっきりさせたいなら Apache-2.0、付けないなら Scorecard の対応を「直さない」にして理由を書く）
2. **著作権者の名前と年。**（おすすめ：`Copyright (c) 2026 Yusukeeeee7`。GitHub のアカウント名なら、本名を新しく公開しない。本名にしたければ教えてほしい）
3. **第三者のデータの説明をどこに書くか。**（おすすめ：`LICENSE` には本文だけを書き、データの出典と条件は直下の `NOTICE.md` に分ける。`LICENSE` に混ぜると GitHub が種類を見分けられず、1 点が入らない見込み。NOAA の条件は書かず、出典の名前とリンクだけにする）
4. **spec のどの機能として扱うか。**（おすすめ：#55 と同じく #24 の「点の低い項目」の 1 つとして扱い、計画を `24-license.md` にする。spec には 10 章（非機能要件）に 1 行足すだけにし、14 章に行は足さない。ライセンスはセキュリティの要件ではないので 11 章ではなく 10 章にする）
5. **`pyproject.toml` に `license = "MIT"` を足すか。**（おすすめ：足さない。パッケージとして配っていない（イメージで配っている）ので読む人がいない。1 つの PR を `LICENSE` に絞る）
6. **Scorecard の点の記録は、マージ後の別の PR（`feature/issues_56-verify`）にし、`Closes #56` をその PR に付けてよいか。**（おすすめ：そうする。#53〜#55 と同じ形）
