# 計画：#24 OpenSSF Scorecard（Issue #46）

状態：承認済み（2026-10-19、人間の回答「OKです」。質問 1〜7 はすべておすすめのとおり）

## 目的と受け入れ条件

spec.md「14. 機能一覧」より：

> | 24 | OpenSSF Scorecard | Scorecard が定期（週 1 回）と main への push で実行され、結果が Security タブに出る。初回の点数と、点の低い項目への対応（直す／直さない理由）を docs に記録する | 未着手 |

spec.md「11. セキュリティ要件」の表（`24 | リポジトリ全体の対策の点数 | OpenSSF Scorecard | Scorecard のワークフロー`）と、共通の決まり（ツールは理由を書いて承認、Action はコミットの SHA で固定、設定・引数・出力は公式ドキュメントで確かめる、指摘は直すか 1 件ずつ理由を書く、通信先を書く、結果にシークレットを出さない）に従う。「13. CI/CD」の「CodeQL と Scorecard は、きっかけが違うので別のワークフローにする」にも従う。

たとえ：工場の「外部の監査員の定期点検」。#18〜#23 は工場の中の検品係（自分で決めた検査を毎回する）。#24 は**外から来た監査員が、決まったチェックリスト（約 20 項目）で工場全体の仕組みを週 1 回採点し、通信簿を事務所の掲示板（Security タブ）に貼る**。点が低い項目は「直す」か「うちでは直さない理由」を記録する。

| 決まり | たとえ | この機能でやること |
|---|---|---|
| 週 1 回と main への push で実行 | 定期点検と、工場を改装したときの臨時点検 | 新しいワークフロー `.github/workflows/scorecard.yml`（`schedule` と `push: main`） |
| 結果が Security タブに出る | 通信簿を掲示板に貼る | SARIF を `github/codeql-action/upload-sarif` でコードスキャンに送る |
| 初回の点数と対応を記録 | 最初の通信簿と、低い項目への返事を残す | `docs/scorecard.md` |

## 調べたこと（2026-10-19）

**1. 公式ドキュメント**（`ossf/scorecard-action` の README、`ossf/scorecard` の `docs/checks.md`。どちらも WebFetch の要約で読んだ。原文は読んでいない。`action.yaml` と公式の例のワークフロー `ossf/scorecard/.github/workflows/scorecard-analysis.yml` は `gh api` で原文を読んだ）：

- きっかけ：`push`（既定のブランチだけ）と `schedule` に対応。`pull_request`・`workflow_dispatch` は実験的。
- 入力（`action.yaml` の原文）：`results_file`（必須）、`results_format`（必須。`json`・`sarif`・`intoto`）、`repo_token`（既定 `${{ github.token }}`）、`publish_results`（既定 false）、`file_mode`（既定 `archive`）、`fail_on_publish_error`（既定 false）。
- 公式の例のワークフロー（原文）：
  - `permissions: read-all`（ワークフロー全体）、ジョブに `security-events: write`（コードスキャンへの送信）と `id-token: write`（`publish_results: true` のときの OIDC トークン）。
  - 手順：`actions/checkout`（`persist-credentials: false`）→ `ossf/scorecard-action@fa7117db83c52d787ae5a89f350999701505d78e # v2.5.0`（`results_file: results.sarif`、`results_format: sarif`、`publish_results: true`）→ `actions/upload-artifact`（任意）→ `github/codeql-action/upload-sarif@24c54180a607b1449ed407dd24f251e4e9147c8d # v4.38.3`（`sarif_file: results.sarif`）。
  - cron は `'30 1 * * 6'`（毎週土曜 01:30 UTC）。
- `publish_results: true` のときの制限（README）：ワークフローの最上位に `env`・`defaults` を書けない、ワークフロー全体に write の権限を書けない、`id-token: write` は Scorecard のジョブだけ。ジョブにも `env`・`defaults`・`container`・`services` を書けない、Ubuntu の GitHub ホストのランナー。使える Action は `actions/checkout`・`actions/upload-artifact`・`github/codeql-action/upload-sarif`・`ossf/scorecard-action`・`step-security/harden-runner` だけ。
- `publish_results: true` にすると、結果が OpenSSF の公開 API（`api.scorecard.dev`）に載り、バッジが使える。public のリポジトリは、もともと OpenSSF が週 1 回スキャンして公開している（それをこのワークフローの結果で置き換える）。
- トークン：既定の `GITHUB_TOKEN` で動く。**クラシックのブランチ保護**の設定を点に反映させるには PAT が要る。リポジトリのルール（Rulesets）は既定のトークンで読める。
- private のリポジトリは GitHub Advanced Security が要る（このリポジトリは public）。
- 結果の見える場所：Security タブ → Code scanning のアラート（数分かかる）、Actions のログとジョブの要約、`publish_results: true` なら `api.scorecard.dev`。

**2. 項目（`docs/checks.md` の要約）**：Binary-Artifacts、Branch-Protection、CI-Tests、CII-Best-Practices、Code-Review、Contributors、Dangerous-Workflow、Dependency-Update-Tool、Fuzzing、License、Maintained、Packaging、Pinned-Dependencies、SAST（CodeQL・SonarCloud だけを数える）、SBOM、Security-Policy（`SECURITY.md`）、Signed-Releases、Token-Permissions、Vulnerabilities（OSV）、Webhooks。

**3. このリポジトリ**（`gh api` で確かめた）：

| 確かめたこと | 結果 |
|---|---|
| 公開状態 | public |
| main のブランチ保護（クラシック） | なし（404「Branch not protected」） |
| Rulesets | なし（空の配列） |
| LICENSE・SECURITY.md | なし |
| コードスキャン（CodeQL の default setup） | `not-configured` |
| Dependabot | `uv`・`github-actions`・`docker`（月 1 回）。`github-actions` は `.github/workflows/` を読むので、新しいワークフローの Action も更新の対象になる |
| ほかのワークフローの Action | すべてコミットの SHA で固定、最上位は `contents: read` |

## 内容

### 1. ワークフロー `.github/workflows/scorecard.yml`

公式の例をもとに、このリポジトリの決まりに合わせる：

```yaml
name: Scorecard

on:
  push:
    branches:
      - main
  schedule:
    - cron: "30 1 * * 6"   # 毎週土曜 01:30 UTC（公式の例と同じ）

permissions:
  contents: read           # ほかのワークフローに合わせる（公式の例は read-all。Token-Permissions はどちらでも満点）

jobs:
  analysis:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    permissions:
      contents: read
      security-events: write   # Security タブ（コードスキャン）に送る
      id-token: write          # publish_results の OIDC トークン（質問 1）
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false
      - uses: ossf/scorecard-action@fa7117db83c52d787ae5a89f350999701505d78e # v2.5.0
        with:
          results_file: results.sarif
          results_format: sarif
          publish_results: true
      - uses: github/codeql-action/upload-sarif@24c54180a607b1449ed407dd24f251e4e9147c8d # v4.38.3
        with:
          sarif_file: results.sarif
```

- SHA は公式の例のもの。`v2.5.0` の SHA は `gh api` でタグから確かめた（`fa7117db…`）。`upload-sarif` は v4.39.0 も出ているが、公式の例と同じ v4.38.3 にし、Dependabot に任せる。
- `upload-artifact` は使わない（質問 4）。
- `repo_token` は渡さない（既定のトークン。PAT は使わない。質問 3）。
- ジョブの `permissions` に `contents: read` を書くか（書かないと none になる）は、公式の例にない。public なので無くても読めるはずだが、実装のときに main での実行のログで「Resource not accessible」などが出ないかを確かめる。
- 手元で actionlint・zizmor（CI と同じイメージ、`--offline`）を実行して指摘がないことを確かめる。

### 2. 記録 `docs/scorecard.md`

- 実行の仕組み（いつ・何を・どこへ送るか）、通信先、結果の見方（Security タブ、ジョブの要約、`api.scorecard.dev`）。
- **初回の点数**：合計点と項目ごとの点（表）。実行の run ID と日付を付ける。
- **点の低い項目への対応**：1 項目ずつ「直す（別の Issue）／直さない（理由）」を書く。たとえば次のものは、実行する前から低くなると予想している（初回の結果で確かめてから書く。予想を結果として書かない）：
  - Branch-Protection（保護なし）、Code-Review（1 人で自分の PR をマージ）、Contributors（1 人）、Maintained（作って 90 日未満）、License・Security-Policy（ファイルなし）、SAST（ruff の `S` は数えられない。CodeQL は #18 で「公開するときに入れる」と決めたまま）、CII-Best-Practices・Fuzzing・Signed-Releases・Packaging。

### 3. spec.md の更新（完了のとき）

- 「11. セキュリティ要件」に Scorecard の 1 行（`docs/scorecard.md` を指す）。
- 「13. CI/CD」の表に `scorecard.yml` の行（きっかけ：週 1 回・main への push。内容）。
- 「14. 機能一覧」の #24 の状態。

### 4. 進め方（2 つの PR。#23 と同じ形）

初回の点数は、main にマージして初めて出る（`push: main` と `publish_results` は既定のブランチだけ）。

1. PR 1（`feature/issues_46`）：ワークフローと `docs/scorecard.md`（仕組みまで。点数の欄は「マージ後に記録」）。
2. マージ後、main の実行が成功し、Security タブに出たことを人間が確かめる（AI は `gh api` で run とコードスキャンのアラートを読む）。
3. PR 2（`feature/issues_46-verify`）：初回の点数と、低い項目への対応を記録し、spec を「完了」にする。

## 今回やらないこと

- 点の低い項目を直すこと（LICENSE・SECURITY.md の追加、ブランチ保護・Rulesets の設定、CodeQL の導入など）。対応を決めて記録し、直すものは別の Issue にする（質問 2）。
- PAT を作って `repo_token` に渡すこと。
- バッジを README に貼ること（spec にない）。
- Scorecard の点で CI を失敗させること（受け入れ条件にない）。

## 変更・追加するファイル
| ファイル | 内容 |
|---|---|
| `.github/workflows/scorecard.yml` | 新規。週 1 回と main への push で Scorecard を実行し、SARIF を Security タブへ送る |
| `docs/scorecard.md` | 新規。仕組み・通信先・結果の見方、初回の点数と項目ごとの対応（点数は PR 2） |
| `docs/spec.md` | 11・13・14 節の更新（完了のとき） |
| `docs/plans/24-scorecard.md` | この計画 |

## テスト一覧（先に書く順）

Python のコードを足さないので、pytest のテストはない（Red → Green にならない。#20〜#23 のワークフローの変更と同じ）。代わりに次の順で確かめる。

| # | 確かめ方 | 種類 | 確かめること |
|---|---|---|---|
| 1 | 手元で actionlint（CI と同じイメージ） | 正常 | 新しいワークフローの書き方に指摘がない |
| 2 | 手元で zizmor `--offline`（CI と同じイメージ） | 正常 | 権限・`persist-credentials`・SHA 固定に指摘がない（指摘が出たら直すか、理由を書いて 1 件ずつ除外） |
| 3 | PR の CI | 正常 | ci.yml の全手順が通る（新しいワークフローも検査される） |
| 4 | マージ後の main の実行（`gh run list --workflow scorecard.yml`） | 正常 | Scorecard のジョブが成功する（push のきっかけ） |
| 5 | Security タブ（人間）と `gh api repos/{owner}/{repo}/code-scanning/alerts?tool_name=Scorecard` | 正常 | 結果がコードスキャンに出ている |
| 6 | ジョブの要約または `api.scorecard.dev` | 正常 | 合計点と項目ごとの点を読み、`docs/scorecard.md` に記録する |
| 7 | 次の土曜の後に `gh run list` | 正常 | `schedule` のきっかけで実行されている（PR 2 の時点で土曜を過ぎていなければ、確かめる日を docs に書いて後で追記） |

## 追加する依存パッケージ
| パッケージ | 理由 | 代替案 |
|---|---|---|
| Action `ossf/scorecard-action` v2.5.0（SHA 固定） | 受け入れ条件の Scorecard を GitHub Actions で動かす公式の方法 | Scorecard の CLI を Docker で動かす（トークンの扱いが増え、Security タブへの送信は別に要る） |
| Action `github/codeql-action/upload-sarif` v4.38.3（SHA 固定） | 結果を Security タブ（コードスキャン）に出すため。public のリポジトリでは無料 | なし（Security タブに出すのはこの方法だけ） |

Python のパッケージは足さない。

## セキュリティ上の注意
- 入力検証：なし（API のコードは変えない）。
- シークレット：使わない。トークンは既定の `GITHUB_TOKEN` だけ（`persist-credentials: false`）。PAT は作らない。結果（SARIF・ログ）に出るのはリポジトリの設定・ファイルの評価で、シークレットは含まれない。
- 権限：ワークフロー全体は `contents: read`。write はジョブの `security-events`・`id-token` だけ（`id-token` は OpenSSF に結果を送るときの本人確認。Scorecard のジョブ以外では使わない）。
- 外部通信（ホスト・タイムアウト）：GitHub の API（リポジトリの設定・履歴を読む）、OSV（Vulnerabilities の検査。正確なホスト名は公式ドキュメントで確かめていないので、実装のときに確かめて書く）、`api.scorecard.dev`（`publish_results` の送信先）。ジョブに `timeout-minutes: 10`。API のコンテナは使わない（アプリは動かさない）。
- `publish_results: true` で結果が公開される。リポジトリは public で、OpenSSF がもともと週 1 回スキャンして公開しているので、新しく漏れる情報はない（質問 1）。

## リスク・未決事項
- ジョブの `permissions` を絞ったとき、Scorecard が読めない項目が出るかもしれない（ログに「Resource not accessible by integration」）。出たら、どの権限を足すかを公式の README の private 用の一覧（`issues: read`・`pull-requests: read`・`checks: read`）から選び、計画に追記する。
- zizmor が新しいワークフローに指摘を出すかは、手元で実行するまで分からない。
- Maintained は作って 90 日たつまで点がつかない。初回の点は、その分だけ低い（記録に書く）。
- `schedule` の実行は main にマージした後の土曜まで確かめられない（テスト一覧の 7）。
- Scorecard の点は、項目ごとの重み付きの平均。点の意味の詳細（-1 や「?」になる項目）は、初回の結果を見てから公式ドキュメントで確かめて書く。

## ブロッカー（人間の対応が必要なこと）
- マージ後に Security タブで結果が出ていることを、人間が画面で確かめる（AI は画面を見られない。`docs/security-settings.md` と同じ扱い）。
- `docs/dast.md`・`docs/dev-log.md`・`docs/spec.md` に、#23 の完了の記録らしき未コミットの変更が main の作業ツリーに残っている。#24 のブランチを作る前に、どう扱うか（#23 の PR にするか）を決める必要がある。

## 質問
1. **`publish_results` を true にしてよいか。**（おすすめ：true。公式の例どおりで、`id-token: write` が要る代わりに `api.scorecard.dev` から点数を読める。リポジトリは public で、もともと OpenSSF が公開スキャンしている。false にすると `id-token` は要らないが、点数はジョブの要約・SARIF からしか読めない）
2. **点の低い項目は、この Issue では「対応を決めて記録する」までにし、直すものは別の Issue にしてよいか。**（おすすめ：別の Issue。1 PR = 1 機能のため。LICENSE の種類やブランチ保護の設定は人間が決めること）
3. **Branch-Protection のために PAT を使わない、でよいか。**（おすすめ：使わない。いまはクラシックの保護も Rulesets もないので、PAT があっても点は変わらない。保護を入れるときは Rulesets にすれば既定のトークンで読める）
4. **SARIF を Actions の成果物（`upload-artifact`）にしない、でよいか。**（おすすめ：しない。結果は Security タブとジョブの要約で読める。#23 でも成果物にしなかった）
5. **cron は公式の例と同じ毎週土曜 01:30 UTC（日本時間 10:30）でよいか。**（おすすめ：それでよい。Dependabot の月 1 回とずれていて、週 1 回の受け入れ条件を満たす）
6. **2 つの PR（ワークフロー → マージ後に初回の点数を記録）で進めてよいか。**（おすすめ：2 つ。#23 と同じ形。点数は main で実行するまで出ない）
7. **main に残っている #23 の記録の変更（`docs/dast.md`・`docs/dev-log.md`・`docs/spec.md`）は、#24 とは別に扱ってよいか。**（おすすめ：別。#23 の記録として先に別の PR にする。#24 のブランチに混ぜない）

## 実装時の変更

- 手元の actionlint（1.7.12）・zizmor（1.30.1、`--offline`。CI と同じイメージ）で、新しいワークフローに指摘はなかった。zizmor の既定で表示されない指摘が 3 件ある（`--persona auditor` で見た）：`undocumented-permissions`（権限の行の同じ行にコメントがない。このファイルでは権限の上の行にコメントを書いている）、`anonymous-definition`（ジョブに `name` がない）、`concurrency-limits`（`concurrency` がない）。`ci.yml`・`cd.yml` にも 3 件ずつ同じように抑えられた指摘があり、CI の既定では失敗にならないので、既存と同じ扱いにした。
- わざと壊して zizmor（CI と同じ設定）が見つけるかを確かめた：
  - `persist-credentials: false` を消す → `artipacked`（medium）で終了コード 13。検出した。
  - `ossf/scorecard-action` を SHA ではなく `@v2.5.0` にする → `unpinned-uses`（high）で終了コード 14。検出した。
  - ワークフロー全体の権限を `contents: write` にする → **検出しなかった**（終了コード 0。抑えられた指摘が 3 → 5 件に増えただけ）。CI の zizmor は既定の重さより低い指摘を出さないため。`publish_results: true` のときは Scorecard の API がワークフロー全体の write の権限を断るが、既定（`fail_on_publish_error: false`）では警告だけになる。
- 上の見逃しへの対応として、`fail_on_publish_error: true` を足した（2026-10-19、人間の回答「おすすめで」）。公式の README の例にもある設定。送信が断られたら（ワークフロー全体に write の権限を書いたときなど）、ジョブが失敗する。気づけるのは main での実行のときで、通信のエラー・408・429・5xx は警告のまま（`action.yaml` の原文の説明）。
