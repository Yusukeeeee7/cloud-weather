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

（初回の点数を見てから、1 項目ずつ「直す（別の Issue）／直さない（理由）」を書く）
