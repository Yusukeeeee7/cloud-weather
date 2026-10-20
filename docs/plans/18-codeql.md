# 計画：#18 SAST の残り CodeQL の導入（Issue #54）

状態：承認済み（2026-10-20、人間の回答「全部おすすめで進めてください」。質問 1〜9 はすべて「おすすめ」で決定）

## 目的と受け入れ条件

Issue #54 の本文（引用）：

> Scorecard の SAST が 0 点（#24、`docs/scorecard.md`）。#18 で「リポジトリを公開するときに CodeQL を入れる」と決め、いまは public なので条件を満たしている。default setup にするか、ワークフローにするかは計画で決める。

spec 14 章 #18 の行（引用）：

> | 18 | SAST | ruff の `S` ルールを有効にし、`ruff check .` が通る。既存の指摘は直すか、理由を書いて 1 件ずつ除外する（テストの `assert` は「11. セキュリティ要件」の例外）。CodeQL は、リポジトリを公開するときに入れる（11 を参照） | 完了（2026-10-16） |

#18 の最初の受け入れ条件（`docs/plans/18-sast.md` に引用。CodeQL を外す前の文言）：

> CodeQL（Python）が PR と main への push で実行され、結果が GitHub の Security タブに出る

spec 11 章の共通の決まり（抜粋）：ツール・Action を足すときは理由を書いて承認を得る、Action は SHA で固定、設定・引数は公式ドキュメントで確かめる、既存の指摘は直すか理由を書いて 1 件ずつ除外する。

この Issue での受け入れ条件（上から）：

1. CodeQL が PR と main への push で実行され、結果が Security タブ（Code scanning）に出る。
2. 危ない書き方をわざと入れた確認用の PR で、CodeQL がそれを指摘する（検品係が本当に見ていることの確認）。
3. 初回の実行で見つかった既存の指摘は、直すか、理由を書いて 1 件ずつ閉じる。
4. 設定と結果を docs に記録し、マージ後の Scorecard の SAST の点を記録する。

たとえ：#18 の ruff の `S` は「ネジの締め忘れを図面と見比べる検品係」。CodeQL は「部品の流れを入口から出口まで追いかける検品係」で、外から来た値（`city` などの入力）が、危ない場所（ファイルを開く・コマンドを実行する・画面に HTML として書く）まで届いていないかを見る。

## 調べたこと（2026-10-20、AI が `gh api` で確認）

**リポジトリの状態**

| 項目 | 結果 |
|---|---|
| 公開 | public（CodeQL は無料で使える） |
| CodeQL の default setup（`GET .../code-scanning/default-setup`） | `not-configured`。default setup にした場合の言語の候補は `actions`・`javascript-typescript`・`python` |
| 言語（`GET .../languages`） | Python、JavaScript（`app/static/app.js`・`compare.js`）、HTML、CSS、Dockerfile、Jupyter Notebook |
| ワークフローでの `github/codeql-action` の利用 | `scorecard.yml` の `upload-sarif`（v4.38.3、SHA `24c54180…`）だけ |
| main の Ruleset | 削除・force push の禁止、PR（承認 0）、必須チェック `ci` だけ |

**Scorecard の SAST の採点**（`ossf/scorecard` の v5.6.0 のソース `checks/evaluation/sast.go`・`checks/raw/sast.go`・`probes/sastToolConfigured`・`probes/sastToolRunsOnAllCommits` と `docs/checks.md` を `gh api` で取得して読んだ）：

- 2 つを見る。
  - (a) ワークフローに `github/codeql-action/analyze` があるか（`uses` が `^github/codeql-action/analyze$` に一致）。`upload-sarif` は数えない（だから今は 0 点）。
  - (b) 最近（約 30）のコミットのうち、マージされた PR の head のコミットに、アプリ `github-advanced-security`・`github-code-scanning`（ほか SonarCloud など）の check run が `success`・`neutral` で付いている割合。
- (a) がある：(b) がすべてなら 10 点。そうでなければ (b) の点 × 3 と 10 点 × 7 の重み付き平均（**入れた直後から 7 点以上の見込み**）。
- (a) がない（default setup の場合）：(b) の割合がそのまま点になる。CodeQL を入れる前の PR が 0 と数えられるので、**入れた直後は 0〜1 点で、PR を約 30 回マージするまで上がりきらない見込み**。
- 実際の点は、マージ後の Scorecard の実行で確かめて記録する（AI が点を予想で書かない）。

**CodeQL のワークフローの形**（GitHub の公式のひな形 `actions/starter-workflows` の `code-scanning/codeql.yml` を `gh api` で取得して読んだ）：

- 手順：`actions/checkout` → `github/codeql-action/init`（`languages`・`build-mode`）→ `github/codeql-action/analyze`（`category: "/language:<言語>"`）。言語ごとに matrix のジョブ。
- 権限：`security-events: write` は必須。`packages: read` は private の CodeQL パックを使うとき、`actions: read`・`contents: read` は private のリポジトリのときだけ要る（ひな形のコメント）。
- ひな形のきっかけは PR・main への push・週 1 回の schedule。
- `github/codeql-action` の最新は `codeql-bundle-v2.27.2`（2026-10-07）。action 自体の版（v4.x）の SHA と、Python の `build-mode`（`none` の見込み）は実装時に公式ドキュメントで確かめる。`scorecard.yml` の `upload-sarif` と同じ SHA にそろえる案（Dependabot が 1 つの PR でまとめて上げる）。

## 進め方（順番）

1. ブランチ `feature/issues_54` で `codeql.yml` を足して PR を出す。この PR で CodeQL が初めて動く（Security タブに初回の結果が出る）。
2. 確認用のブランチ `feature/issues_54-fail` で、危ない書き方をわざと入れた PR を出し、CodeQL が指摘することを確かめて、**マージせずに閉じる**（質問 6。ブランチは消さない）。
3. 初回の結果（既存の指摘）を `gh api .../code-scanning/alerts?tool_name=CodeQL` で読み、直すか、閉じる理由を書く（質問 5）。
4. 記録（`docs/security-settings.md`・spec）を `feature/issues_54` に足し、人間がマージする。
5. マージで main への push が起き、CodeQL と Scorecard が動く。点を記録する別の PR（`feature/issues_54-verify`）を出す。**`Closes #54` はこの最後の PR に付ける**（質問 8）。

## 今回やらないこと

- default setup（質問 1 のおすすめの場合）。
- Ruleset に CodeQL を必須のチェックとして足すこと、Rulesets の「Code scanning results」のルール（質問 7）。
- `security-extended` などの追加のクエリ（質問 4）。
- CodeQL の `actions` 言語（zizmor・actionlint が見ている）（質問 3）。
- ruff の `S`（#18）の変更、SonarCloud など別の道具。
- SECURITY.md（#55）・ライセンス（#56）。

## 変更・追加するファイル

| ファイル | 内容 |
|---|---|
| `.github/workflows/codeql.yml` | 新規。きっかけは PR（main 向け）と main への push（質問 2）。最上位は `contents: read`、ジョブは `contents: read`・`security-events: write`。matrix で `python`・`javascript-typescript`（質問 3）、`build-mode: none`。`actions/checkout` は `persist-credentials: false`、`timeout-minutes` を付ける。Action は SHA で固定し、版をコメントに書く。同じ PR の古い実行を止める `concurrency` は `ci.yml` に合わせる |
| `docs/plans/18-codeql.md` | この計画 |
| `docs/security-settings.md` | 18 行目「CodeQL analysis は未設定」を更新。CodeQL の節：ワークフロー、結果の見方、初回の指摘と対応（1 件ずつ） |
| `docs/spec.md` | 14 章 #18 の受け入れ条件と状態。11 章の表の #18 の行に CodeQL を足し、「private では有料…公開するときに入れる」の段落を「public にしたので入れた（#54）。private に戻すと使えない」に。13 章の表に `codeql.yml` の行 |
| `docs/scorecard.md` | 別の PR（手順 5）：「点の低い項目への対応」の SAST の行と、設定後の点 |
| `app/`・`tests/` など | 初回の指摘を直す場合だけ（質問 5）。直すときは TDD（直す前に失敗するテストを先に書く） |
| `docs/dev-log.md` | `/dev-log` で記録 |
| （確認用、マージしない）`app/` のどれか 1 ファイル | `feature/issues_54-fail` だけで、危ない書き方を 1 か所足す。main には入らない |

テストへの影響を検索した結果：`codeql`・`code-scanning` を参照するテストはない（2026-10-20 に `tests/`・`scripts/`・`app/`・`ml/` を `codeql`・`code-scanning`・`code_scanning` で検索して 0 件）。`ci.yml` は変えないので、必須チェック `ci` には影響しない。

## テスト一覧（確かめる順）

ワークフローの追加なので、pytest ではなく確かめのシナリオにする。TDD の「Red」にあたるのはシナリオ 3（わざと入れた危ない書き方が指摘される）。

| # | シナリオ | 種類 | 確かめること |
|---|---|---|---|
| 0 | 追加の前に `GET .../code-scanning/analyses?tool_name=CodeQL` | 異常（Red） | CodeQL の解析が 0 件（いまは何もない）。設定前の記録 |
| 1 | 手元で actionlint・zizmor（CI と同じイメージ・同じ引数を Docker で） | 正常 | `codeql.yml` に指摘がない。CI でも同じ手順が通る |
| 2 | この PR の CodeQL の実行 | 正常 | `python`・`javascript-typescript` の 2 つのジョブが成功し、`GET .../code-scanning/analyses` に 2 つの category（`/language:python`・`/language:javascript-typescript`）が出る。PR に CodeQL の check run（アプリ `github-advanced-security` か `github-code-scanning`）が付く（Scorecard の (b) が数えるもの）。人間が Security タブで結果を見る |
| 3 | 確認用 PR（危ない書き方を 1 か所） | 異常（Red） | CodeQL がその行をアラートとして出す。入れる書き方とクエリ（例：入力をそのままファイルの道に使う → `py/path-injection`）は、CodeQL の公式のクエリの説明で確かめてから決める。マージせずに閉じる |
| 4 | 初回の既存の指摘 | 結果で中身が変わる（Red にならない） | `gh api` で読んだ全件が、直したか、理由を書いて閉じたかのどちらかになっている（0 件なら 0 件と記録） |
| 5 | 既存の全テスト・ruff・mypy・nbmake | 正常（Red にならない。いまの動作を守る） | 指摘を直してコードを変えた場合も、すべて通る |
| 6 | マージ後の main への push の実行 | 正常 | CodeQL が main で成功し、Security タブの main の結果になる |
| 7 | マージ後の Scorecard の実行 | 結果で中身が変わる（Red にならない） | SAST が 0 より上になる。点・理由・details を `api.scorecard.dev` の JSON から写して記録する。見込み（7 以上）と違ったら理由を出力から読んで書く |

## 追加する依存パッケージ

Python のパッケージはなし。外部 Action を 2 つ足す（`github/codeql-action` は `scorecard.yml` ですでに使っている）。

| Action | 理由 | 代替案 |
|---|---|---|
| `github/codeql-action/init`・`analyze`（SHA で固定、Dependabot の `github-actions` が更新） | CodeQL の解析を行う公式の Action。Scorecard が SAST として数えるのはこの `analyze` | default setup（ファイルは要らないが、Scorecard の (a) に入らない。質問 1） |

## セキュリティ上の注意

- 入力検証：アプリの入力検証は変えない（指摘を直す場合を除く）。
- シークレット：使わない。トークンは既定の `GITHUB_TOKEN`。`actions/checkout` は `persist-credentials: false`。
- 権限：最上位は `contents: read`、ジョブだけ `security-events: write`。`actions: read`・`packages: read` は public で既定のパックだけなので付けない（ひな形のコメント）。
- 外部通信：GitHub のランナーの中で、CodeQL のバンドルの取得（GitHub のホスト）と Security タブへの結果の送信。アプリのコンテナは使わない。
- `pull_request_target` は使わない（フォークからの PR にトークンを渡さない）。zizmor が見る。

## リスク・未決事項

- **既存の指摘の数は、実行するまで分からない。** 多ければ、直すものを別の Issue に分けるかを、そのときに聞く（質問 5）。
- **`tests/fixtures/` の HTML（USNO のページ）を JavaScript として解析する可能性。** 外から保存したページの中のスクリプトに指摘が出たら、`paths-ignore` で `tests/fixtures/` を外すかを聞く（まとめての除外になるので、理由を書いて承認を得る）。
- **CodeQL の check run が Scorecard に数えられるか。** アプリの名前（`github-advanced-security` か `github-code-scanning`）は、この PR の check run を `gh api` で読んで確かめる。
- **CI の時間が増える。** public なので Actions の時間は無料。PR ごとに CodeQL の 2 つのジョブが `ci` と並んで動く。
- **Dependabot の `github-actions` の PR で、`scorecard.yml` と `codeql.yml` の `codeql-action` の SHA が同時に上がる。** グループ `actions` で 1 つの PR になる。
- **`fail` の確認用 PR のアラート**は、その PR の ref に付き、main の結果には入らない見込み。閉じたあと Security タブに残るかを確かめて記録する。
- **リポジトリを private に戻すと、CodeQL が動かなくなる**（ライセンスが要る）。spec 11 章に書く。

## ブロッカー（人間の対応が必要なこと）

- Security タブの画面での確認（シナリオ 2・3）。AI は `gh api` で読み、人間が画面で確かめる。
- 既存の指摘を閉じる（dismiss）場合の操作（質問 5）。
- この PR と `-verify` の PR のマージ。
- spec 7 章の外部 API の項目は使わない。ブロッカーなし。

## 質問

未回答：なし

回答済み（2026-10-20、人間の回答「全部おすすめで進めてください」）：ワークフロー（`codeql.yml`）、きっかけは PR と main への push、言語は `python`・`javascript-typescript`、クエリは既定、初回の指摘は AI が一覧にして直せるものは TDD で直し、直さないものは人間が理由つきで dismiss（10 件を超えたら分けるかを聞く）、`-fail` の確認用 PR を作る、Ruleset の必須チェックにはしない、点の記録は `-verify` の PR で `Closes #54` もそこに付ける、計画の番号は `18-codeql.md`。

以下は、レビューのときに示した質問の原文。

1. **default setup とワークフロー（advanced setup）のどちらにするか。**
   - **おすすめ：ワークフロー（`codeql.yml`）**。Scorecard は `github/codeql-action/analyze` のあるワークフローを数えるので、入れた直後から 7 点以上の見込み（default setup だと、PR を約 30 回マージするまで点が上がりきらない）。設定がコードに残ってレビューでき、ほかの Action と同じく SHA の固定・Dependabot・zizmor・actionlint の対象になる。spec 13 章の「CodeQL と Scorecard は別のワークフロー」とも合う。
   - 代案：default setup。ファイルが要らず、更新は GitHub 任せ。設定は画面にだけ残る。
2. **きっかけ**：（おすすめ：PR と main への push だけ。#18 の最初の受け入れ条件のまま。毎週の schedule（新しいクエリで古いコードを見直す）は、main へのマージが多いので入れない）
3. **解析する言語**：#18 の最初の条件は Python だけ。
   - **おすすめ：`python` と `javascript-typescript`**。画面の JS（`app.js`・`compare.js`）は API の値を画面に書くので、HTML として書く（XSS）の検査に意味がある。並んで動くので時間はほとんど増えない。
   - `actions` は入れない（zizmor・actionlint が見ている）。
   - 代案：`python` だけ（spec のとおり）。
4. **クエリの組（query suite）**：（おすすめ：既定（`default`）。誤検知が少なく、指摘の 1 件ずつの対応が重くならない。`security-extended` は後で別の Issue にできる）
5. **初回の既存の指摘の扱い**：（おすすめ：AI が `gh api` で読んで一覧にし、直せるものはこの Issue で TDD で直す。直さないもの（誤検知・テストのコードなど）は、理由を docs に書き、人間が Security タブで 1 件ずつ dismiss する。10 件を超えたら、直す作業を別の Issue に分けるかをそのとき聞く。AI は dismiss（書き込み）をしない）
6. **確認用の PR（`feature/issues_54-fail`）で、危ない書き方をわざと入れて、マージせずに閉じてよいか。**（おすすめ：作る。CodeQL が本当に見ていることを確かめる唯一の方法で、#53 の `-fail` と同じ形。ブランチは消さない）
7. **CodeQL を Ruleset の必須チェックにするか。**（おすすめ：今回はしない。受け入れ条件は「実行され、結果が Security タブに出る」だけで、必須にすると check run の名前の設定を間違えたときにマージできなくなる（#53 で 2 回やり直した）。入れるなら別の Issue）
8. **Scorecard の点の記録は、マージ後の別の PR（`feature/issues_54-verify`）にし、`Closes #54` をその PR に付けてよいか。**（おすすめ：そうする。#53 と同じ形。点はマージ後の実行でしか分からない）
9. **計画の番号**：Issue #54 は spec #18（SAST）の残りとして扱い、計画を `18-codeql.md` にした。spec の #18 の状態は、受け入れ条件 1〜3 がそろった時点で「完了（CodeQL は 2026-10-xx、#54）」に書き換える。（おすすめ：このまま）

## 実装時の変更

- **Action の版**（2026-10-20、`gh api repos/github/codeql-action/tags` で確認）：v4.38.3 のコミットは `24c54180a607b1449ed407dd24f251e4e9147c8d` で、`scorecard.yml` の `upload-sarif` と同じ。最新は v4.39.0 だが、`scorecard.yml` とそろえるため v4.38.3 にした（Dependabot の `actions` のグループがまとめて上げる）。
- **入力**（同じ SHA の `init/action.yml`・`analyze/action.yml` の原文を `gh api` で取得して読んだ）：`languages`・`build-mode`（matrix で 1 ジョブ 1 言語のときだけ使える。`none` は「すべてのインタープリタ型の言語」で使える）・`category`。`analyze` の `upload` の既定は `always`、`token` は既定の `GITHUB_TOKEN` に任せる（`security-events: write` が要る）。Python・JS のビルドの要否について、GitHub の docs の原文は読んでいない（action.yml の説明による）。
- **`concurrency`**（計画は「`ci.yml` に合わせる」）：`codeql.yml` は main への push でも動くので、グループを `codeql-<PR 番号 か コミットの SHA>` にし、古い実行を止めるのは PR のときだけにした（main の解析を途中で止めないため）。
- **シナリオ 1**：手元の Docker で、CI と同じイメージ・引数の actionlint（終了コード 0）と zizmor（`No findings to report`、終了コード 0）が通った。
- **シナリオ 2・4**：PR #64 で 2 つのジョブと `CodeQL`（アプリ `github-advanced-security`）が成功。初回の指摘は 0 件で、直すもの・閉じるものはなかった（質問 5 の手順は使わなかった）。`tests/fixtures/` の HTML の指摘も出なかったので、`paths-ignore` は足していない。
- **シナリオ 3 の書き方**：CodeQL の `py/path-injection` の原文（`github/codeql` の `PathInjection.ql`。`@precision high`、`@problem.severity error`）と、FastAPI の引数を外からの入力として扱う `FastApi.qll` を `gh api` で取得して読んでから決めた。`app/routers/health.py` に `@router.get("/debug-file")` で `Path(path).read_text()` を返す関数を足した（ruff が通る形にした）。結果はアラート #10（22 行目）。
- **必須チェックでないことの影響**（計画に書いていなかった）：PR #65 は `CodeQL` が `failure` でも `mergeStateStatus: UNSTABLE` でマージできる状態だった。質問 7 の決定どおりで、`docs/security-settings.md` に書いた。
