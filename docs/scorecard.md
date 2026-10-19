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
| 失敗の扱い | 点が低くても失敗にしない（受け入れ条件にない）。`api.scorecard.dev` への送信が断られたら失敗にする（`fail_on_publish_error: true`。ワークフロー全体に write の権限を書いたときなど。CI の zizmor は既定ではこれを見つけない）。通信のエラー・408・429・5xx は警告だけ |

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

（main にマージした後の実行で記録する。PR 2：`feature/issues_46-verify`）

## 点の低い項目への対応

（初回の点数を見てから、1 項目ずつ「直す（別の Issue）／直さない（理由）」を書く）
