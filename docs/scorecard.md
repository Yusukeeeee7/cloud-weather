# OpenSSF Scorecard（#24、Issue #46）

外から来た監査員が、決まったチェックリストでリポジトリ全体の対策を週 1 回採点し、通信簿を掲示板（Security タブ）に貼る仕組み。
#18〜#23 は工場の中の検品係（自分で決めた検査を毎回する）。Scorecard は外部の決まった基準での点検で、点の低い項目は「直す」か「直さない理由」を記録する。

## 実行の仕組み

| 項目 | 内容 |
|---|---|
| ワークフロー | `.github/workflows/scorecard.yml` |
| きっかけ | main への push、毎週土曜 01:30 UTC（日本時間 10:30） |
| 使う Action | `ossf/scorecard-action` v2.5.0、`github/codeql-action/upload-sarif` v4.38.3（どちらもコミットの SHA で固定。Dependabot の `github-actions` が更新する） |
| トークン | 既定の `GITHUB_TOKEN`（PAT は使わない）。`actions/checkout` は `persist-credentials: false` |
| 権限 | ワークフロー全体は `contents: read`。ジョブは `contents: read`・`security-events: write`（Security タブへの送信）・`id-token: write`（`publish_results` の本人確認） |
| 結果の送り先 | Security タブ（コードスキャン。SARIF）、`api.scorecard.dev`（`publish_results: true`） |
| 失敗の扱い | 点が低くても失敗にしない（受け入れ条件にない）。`api.scorecard.dev` への送信が断られても、警告だけで失敗しない（下の「見つけられないこと」） |

### 見つけられないこと

- **ワークフロー全体に write の権限を書いても、どこも失敗しない。** README の制限によれば、そのときは `api.scorecard.dev` への送信が断られるはずだが（実際に断られるかは未確認）、v2.5.0 では断られても警告だけになる。CI の zizmor も、既定の設定ではこの権限を指摘しない（#24 の実装のとき、わざと壊して確かめた）。気づけるのは、Scorecard の Token-Permissions の点が下がったとき。
- 送信が断られたら失敗にする入力 `fail_on_publish_error` は、v2.5.0 の後（2026-10-14）に main に足されたもので、v2.5.0 にはない。#50 では main の `action.yaml` を読んで足してしまい、初回の実行で `Unexpected input(s) 'fail_on_publish_error'` の警告が出て、読まれていないことが分かった（2026-10-19 に削除）。この入力を持つ版が出て Dependabot が更新したら、入れ直すかを別の Issue で決める。

- `publish_results: true` のときの制限（scorecard-action の README。WebFetch の要約で読んだ）：ワークフローの最上位に `env`・`defaults`・write の権限を書けない。ジョブにも `env`・`defaults`・`container`・`services` を書けない。使える Action は `actions/checkout`・`actions/upload-artifact`・`github/codeql-action/upload-sarif`・`ossf/scorecard-action`・`step-security/harden-runner` だけ。このワークフローに手順を足すときは、この制限を守る。
- リポジトリは public で、OpenSSF がもともと週 1 回スキャンして結果を公開している。`publish_results: true` は、その結果をこのワークフローの結果で置き換える（新しく公開される情報はない）。
- リポジトリを private に戻すと、GitHub Advanced Security がないかぎり使えない（README）。

## 通信先

- GitHub の API（リポジトリの設定・履歴・ワークフローを読む。Security タブへの送信）
- `api.scorecard.dev`（`publish_results` の送信先）
- OSV（Vulnerabilities の検査。正確なホスト名は確かめていない）

アプリのコンテナは使わない（API は動かさない）。

## 結果の見方

- Security タブ → Code scanning → ツール「Scorecard」のアラート（項目ごと。直し方の説明つき）。数分かかる。
- Actions の実行のログ（項目ごとの点と合計点）。
- `https://api.scorecard.dev/projects/github.com/Yusukeeeee7/cloud-weather`（JSON。合計点と項目ごとの点）。
- AI は画面を見られないので、`gh run list --workflow scorecard.yml`・`gh api .../code-scanning/alerts?tool_name=Scorecard` で読み、人間が Security タブで確かめる。

## 初回の点数

**合計 5.3 / 10**（2026-10-19T12:32Z。#50 のマージ後の main への push の実行、run 39252804563、コミット `3476c36`。Scorecard v5.6.0）

- 表は `https://api.scorecard.dev/projects/github.com/Yusukeeeee7/cloud-weather` の JSON を保存し、`checks` から行ごとに作った（手で写していない）。理由の欄は Scorecard の出力のまま。
- -1 は「採点できない」で、合計に入らない（Signed-Releases はリリースがないため）。
- Security タブ（コードスキャン）には、0 点・8 点の項目のうち 9 件がアラートとして出た（Branch-Protection・License・Fuzzing・SAST・Security-Policy・Code-Review・Maintained・CII-Best-Practices・CI-Tests。Contributors は出ていない）。`gh api .../code-scanning/alerts?tool_name=Scorecard` で確かめた。
- ジョブ全体は 38 秒。送信（`publish_results`）は成功した（上の API に結果が載った）。

| 項目 | 点 | 理由（Scorecard の出力） |
|---|---|---|
| Binary-Artifacts | 10 | no binaries found in the repo |
| Dangerous-Workflow | 10 | no dangerous workflow patterns detected |
| Dependency-Update-Tool | 10 | update tool detected |
| Packaging | 10 | packaging workflow detected |
| Pinned-Dependencies | 10 | all dependencies are pinned |
| Token-Permissions | 10 | GitHub workflow tokens follow principle of least privilege |
| Vulnerabilities | 10 | 0 existing vulnerabilities detected |
| CI-Tests | 8 | 6 out of 7 merged PRs checked by a CI test -- score normalized to 8 |
| Branch-Protection | 0 | branch protection not enabled on development/release branches |
| CII-Best-Practices | 0 | no effort to earn an OpenSSF best practices badge detected |
| Code-Review | 0 | Found 0/7 approved changesets -- score normalized to 0 |
| Contributors | 0 | project has 0 contributing companies or organizations -- score normalized to 0 |
| Fuzzing | 0 | project is not fuzzed |
| License | 0 | license file not detected |
| Maintained | 0 | project was created within the last 90 days. Please review its contents carefully |
| SAST | 0 | SAST tool is not run on all commits -- score normalized to 0 |
| Security-Policy | 0 | security policy file not detected |
| Signed-Releases | -1 | no releases found |

## 点の低い項目への対応

2026-10-19、人間の回答「全部おすすめで進めて」で決めた。直すものは、それぞれ別の Issue にする（この Issue では直さない）。

| 項目 | 点 | 対応 | 理由 |
|---|---|---|---|
| Branch-Protection | 0 | 直した（#53。設定後は 3 点。下の「設定後の点」） | main に Rulesets を設定する（force push・削除の禁止、CI の成功を必須に）。spec #2 の「ブランチ保護の設定が残っている」と同じ作業。Rulesets は既定の `GITHUB_TOKEN` で Scorecard が読める（README）ので、PAT は要らない |
| SAST | 0 | 直した（#54。設定後は 7 点。下の「設定後の点（SAST）」） | CodeQL。#18 で「リポジトリを公開するときに入れる」と決め、いまは public なので条件を満たしている。ruff の `S` ルール（#18）は Scorecard の数える道具に入っていない（数えるのは CodeQL・SonarCloud など） |
| Security-Policy | 0 | 直す（別の Issue） | `SECURITY.md` を置き、脆弱性の報告の窓口を書く（GitHub の非公開の脆弱性報告を使う予定。設定は Issue で確かめる） |
| License | 0 | 人間が決める（別の Issue） | 付けるか、どのライセンスにするかは持ち主が決めること |
| Code-Review | 0 | 直さない | 1 人で開発していて、承認する人がいない。承認を必須にすると、自分でマージできなくなる |
| Contributors | 0 | 直さない | 個人の学習用のリポジトリ。直す方法は、ほかの組織の参加者を増やすことだけ |
| Maintained | 0 | 直さない（時間で直る） | 作って 90 日たつまで点がつかない |
| Fuzzing | 0 | 直さない（いまは） | Python でのファジングには依存の追加が要る。API の入力は、`city` の許可リストと数値の範囲の検査だけ |
| CII-Best-Practices | 0 | 直さない | 外部のサイト（OpenSSF Best Practices）での自己申告で、このリポジトリの学習の目的から外れる |
| CI-Tests | 8 | 直さない | 7 つの PR のうち 1 つで、CI の成功が数えられていない。直近にマージした 7 つ（#40・#42・#44・#47・#48・#49・#50）のうち、head のコミットの CI が成功していないのは #48（`cancelled`。dev-log の #23 の記録のとおり、dev-log のコミットの CI が途中で止まったままマージした）だけ。Scorecard がどの 7 つを見たかは出力にないので、これは `gh api` で各 PR の check run を見た推定 |
| Signed-Releases | -1 | 対象外 | GitHub のリリースを作っていない。配布しているイメージには #22 で来歴と SBOM を付けている |

## 設定後の点（Branch-Protection、#53）

**合計 5.5 / 10、Branch-Protection 3 / 10**（2026-10-20T12:19:33Z。PR #61 のマージ後の main への push の実行、run 39421355472、コミット `a1dfe38`。Scorecard v5.6.0）

- `api.scorecard.dev` の JSON を保存し、Branch-Protection の `score`・`reason`・`details` をそのまま写した（手で写していない）。ほかの項目の点は見ていない（合計が 5.3 から 5.5 に上がったことだけ）。
- 設定の中身は `docs/security-settings.md` の「main のブランチ保護」。
- 理由：branch protection is not maximal on development and all release branches

| 判定 | details（Scorecard の出力） |
|---|---|
| Info | 'allow deletion' disabled on branch 'main' |
| Info | 'force pushes' disabled on branch 'main' |
| Info | 'branch protection settings apply to administrators' is required to merge on branch 'main' |
| Info | status check found to merge onto on branch 'main' |
| Info | PRs are required in order to make changes on branch 'main' |
| Warn | 'stale review dismissal' is disabled on branch 'main' |
| Warn | branch 'main' does not require approvers |
| Warn | codeowners review is not required on branch 'main' |
| Warn | 'last push approval' is disabled on branch 'main' |
| Warn | 'up-to-date branches' is disabled on branch 'main' |

- 点の見方（公式の `docs/checks.md` の Branch-Protection の節。#53 の計画のとき `gh api` で原文を取得して読んだ）：段 1（force push・削除の禁止）を満たして 3 点。段 2 は「承認 1 人以上」を満たさないので、段 3 の必須チェック（`status check found`）は点に入らない。計画の見込み（3 以上 6 未満）の範囲。
- 段 2 で「管理者」と付いた条件（PR の必須、最新の取り込み、最後の push の承認）は、既定のトークンでは満たしたものとして数える、と `checks.md` にある。それでも details には `'up-to-date branches' is disabled` などの Warn が出た。Rulesets は既定のトークンで読めるので、読めた値をそのまま出しているのだと思われるが、点の計算でどう扱われたかは確かめていない。
- これ以上上げるには、承認の必須（段 2）が要る。1 人の開発なので入れない（Code-Review と同じ理由）。

## 設定後の点（SAST、#54）

**合計 5.9 / 10、SAST 7 / 10**（2026-10-20T13:30:07Z。PR #64 のマージ後の main への push の実行、run 39430900807、コミット `74c7716`。Scorecard v5.6.0）

- `api.scorecard.dev` の JSON を保存し、SAST の `score`・`reason`・`details` をそのまま写した（手で写していない）。ほかの項目の点は見ていない（合計が 5.5 から 5.9 に上がったことだけ）。
- 設定の中身は `docs/security-settings.md` の「CodeQL」。
- 理由：SAST tool detected but not run on all commits

| 判定 | details（Scorecard の出力） |
|---|---|
| Info | SAST configuration detected: CodeQL |
| Warn | 4 commits out of 30 are checked with a SAST tool |

- 点の見方（`ossf/scorecard` の v5.6.0 のソース `checks/evaluation/sast.go` を、#54 の計画のとき `gh api` で取得して読んだ）：ワークフローに `github/codeql-action/analyze` があると (a) が 10 点。(b) は最近の 30 のコミットのうち、マージした PR の head に CodeQL などの check run が付いている割合。(a) があり (b) がすべてでないときは、(b) × 3 と (a) × 7 の重み付きの平均になる。計画の見込み（7 以上）の範囲。
- 「4 commits out of 30」：CodeQL の check run が付いているのは PR #64 だけで、PR #64 のコミット（3 つ）とマージのコミットがそれぞれ PR #64 に結びつくので 4 と数えられたと思われる（Scorecard の出力にどのコミットかは出ないので、確かめていない）。
- これからマージする PR が CodeQL を通るたびに (b) が上がり、最近の 30 のコミットがすべてそうなれば 10 点になる見込み。直すことはない（時間で上がる）。
