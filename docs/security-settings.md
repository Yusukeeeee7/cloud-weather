# GitHub のセキュリティの設定（人間が設定画面で確かめた記録）

GitHub の設定は、コードやワークフローのファイルに残らない。人間が設定画面で見た状態を、ここに日付つきで記録する。
AI は設定画面を見られないので、人間のスクリーンショットか、AI が `gh api` で読んだ結果をもとに書く（どちらで書いたかを節ごとに書く）。

## シークレットのコミット防止（#19、Issue #36）

確かめた日：2026-10-16。リポジトリは public。

| 設定画面 | 欄 | 状態 | 画面の説明文 |
|---|---|---|---|
| リポジトリの Settings → Code security →「Secret Protection」 | Secret Protection（secret scanning） | 有効（右のボタンが「Disable」） | Continuously monitor this repository to prevent secret exposures and protect credentials. GitHub will always send alerts to partners for detected secrets in public repositories. |
| 同上 | Push protection | 有効（同上） | Block commits that contain supported secrets. |
| プロフィールの Settings → Code security →「User」 | Push protection for yourself | 有効（同上） | Block commits that contain supported secrets across all public repositories on GitHub. |

- Secret Protection と Push protection は、この日に人間が「Enable」を押して有効にした（それまでは無効）。
- 「Push protection for yourself」は、画面の説明文のとおり public のリポジトリへの push に効く。
- 同じ画面の CodeQL analysis は、この時点では未設定だった（#18 で「公開するときに入れる」と決めたもの）。2026-10-20 に default setup ではなくワークフローで入れた（下の「CodeQL（#18 の残り、Issue #54）」）。

役割の分担：

| 係 | どこで | 何をする |
|---|---|---|
| Push protection（GitHub） | push を受け取るとき | 対応している形の鍵が入ったコミットの push を止める |
| Secret Protection（GitHub） | リポジトリに入ったあと | 鍵が入っていないかを見続け、見つけたら知らせる |
| gitleaks（CI、`ci.yml`） | PR ごと | 全履歴を検査し、見つかったら CI を失敗にする |

## main のブランチ保護（#2、Issue #53）

設定した日：2026-10-20。人間が設定画面（Settings → Rules → Rulesets）で作り、AI が `gh api`（`repos/.../rulesets/25472510` と `repos/.../rules/branches/main`）で読んで確かめた。下の表は `gh api` の結果から作った（画面のスクリーンショットではない）。

たとえると、出荷口（main）の門番。検品係（CI）の合格札がない箱は通さず、出荷口を壊すことも、出荷済みの箱をすり替えることも止める。持ち主（管理者）も例外にしない。

| 項目 | 値（`gh api` の項目） | 意味 |
|---|---|---|
| Ruleset | id `25472510`、名前 `main`、`enforcement: active` | 有効 |
| 対象 | `~DEFAULT_BRANCH` | 既定のブランチ（main） |
| バイパス | `bypass_actors: []`、`current_user_can_bypass: never` | 例外なし（管理者も） |
| 削除の禁止 | `deletion` | main を消せない |
| force push の禁止 | `non_fast_forward` | main の履歴を書き換えられない |
| PR の必須 | `pull_request`、`required_approving_review_count: 0` | main に直接 push できない。承認は要らない（1 人の開発のため） |
| 必須チェック | `required_status_checks`：`context: ci`、`integration_id: 15368` | `ci.yml` のジョブ `ci` が成功しないとマージできない。`15368` は GitHub Actions のアプリ（`gh api apps/github-actions` で確認） |
| 最新の main の取り込み | `strict_required_status_checks_policy: false` | 必須にしない（#2 の決定。1 人の開発で PR が並ばない） |
| Copilot の PR の追加の承認 | `require_extra_approval_for_unattributed_changes: true` | 選んでいない既定値。人ではなく Copilot が開いた PR で承認を 1 つ増やす設定で、**承認 0 のときは効かない**（公式ドキュメント「Available rules for rulesets」の原文を `github/docs` から取得して読んだ、2026-10-20） |

確かめたこと：

| # | 確かめ方 | 結果 |
|---|---|---|
| 0 | 設定の前に `GET rules/branches/main` | `[]`（何も効いていない） |
| 1・2 | `GET rulesets/25472510`、`GET rules/branches/main` | 上の表のとおり。4 つのルールが main に効いている |
| 3 | わざとテストを 1 件失敗させる PR #62（ブランチ `feature/issues_53-fail`） | `ci`（run 39419042616）が `failure`（`Pytest (coverage)` で `test_fails_on_purpose` だけが失敗）。`mergeStateStatus: BLOCKED`。人間が画面でマージできないことを見た。マージせずに閉じ、ブランチは残した |
| 4 | この記録の PR #61（docs だけ） | 計画だけのコミット `1718d0c` のとき、`ci` が成功して `mergeStateStatus: CLEAN`、人間が画面でマージできることを見た。記録を足したコミット `d6182b1` でも、`ci`（run 39419961287）が成功して `CLEAN`（AI が `gh pr view` で確認） |

- 直接の push・force push・削除は、実際には試していない（設定が間違っていたら main が書き換わるため）。`GET rules/branches/main` で効いているルールを読んで代えた。
- 設定のとき、必須チェックの検索欄の文字が候補を選ぶ前に登録され、チェックの名前が `required_status_checks` になった。この名前のチェックはどのワークフローも出さないので、PR #61 は `ci` が成功していても `BLOCKED` になった。候補の一覧から `ci` を選び直して直した。**必須チェックを変えたら、`gh api` で `context` の名前を確かめる。**
- 必須チェックは名前 `ci` に結びつく。`ci.yml` のジョブの名前を変えるときは、Ruleset も同時に変える。
- `ci` が `cancelled`（`ci.yml` の `cancel-in-progress` で古い実行が止められた）のままだとマージできない。そのときは CI を再実行する。

CI が壊れて誰もマージできなくなったとき：

1. 人間が Settings → Rules → Rulesets → `main` の Enforcement status を **Disabled** にする。
2. 直す PR をマージする。
3. **Active** に戻し、`gh api repos/.../rulesets/25472510 --jq .enforcement` が `active` になったことを確かめる。

## CodeQL（#18 の残り、Issue #54）

入れた日：2026-10-20。設定画面の default setup ではなく、ワークフロー `.github/workflows/codeql.yml` で入れた（設定はファイルに残る）。下の結果は、AI が `gh api`（`code-scanning/analyses`・`code-scanning/alerts`・`commits/<SHA>/check-runs`）で読んだもの。

たとえると、部品の流れを入口から出口まで追いかける検品係。外から来た値（API の入力）が、ファイルを開く・画面に HTML として書くなどの危ない場所まで届いていないかを見る。#18 の ruff の `S`（図面と見比べる係）と役割が違う。

| 項目 | 値 |
|---|---|
| きっかけ | main 向けの PR、main への push |
| 言語 | `python`（`/language:python`）、`javascript-typescript`（`/language:javascript-typescript`）。どちらも `build-mode: none` |
| クエリ | 既定の組（Python 43 ルール、JS 87 ルール。初回の解析の `rules_count`） |
| Action | `github/codeql-action/init`・`analyze` v4.38.3（`scorecard.yml` の `upload-sarif` と同じ SHA） |
| 権限 | 最上位 `contents: read`、ジョブ `contents: read`・`security-events: write` |
| PR に付く check run | ジョブの `Analyze (python)`・`Analyze (javascript-typescript)`（アプリ `github-actions`）と、結果の `CodeQL`（アプリ `github-advanced-security`）。Scorecard の SAST が数えるのは後者 |
| マージとの関係 | Ruleset の必須チェックではない。新しいアラートで `CodeQL` が `failure` になっても、マージは止まらない（`mergeStateStatus: UNSTABLE`）。PR の画面で見て直す |

確かめたこと：

| # | 確かめ方 | 結果 |
|---|---|---|
| 0 | 入れる前に `GET code-scanning/analyses?tool_name=CodeQL`・`alerts?tool_name=CodeQL` | どちらも 0 件（コードスキャンには Scorecard の解析 21 件だけ） |
| 1 | 手元の Docker で、CI と同じ actionlint・zizmor | どちらも指摘なし |
| 2 | 入れた PR #64（コミット `7f6933e`） | `Analyze (python)`・`Analyze (javascript-typescript)`（run 39425225068）が成功。`CodeQL`（`github-advanced-security`）も `success`。解析が 2 つの category で 1 つずつでき、指摘は **0 件** |
| 3 | わざと危ない書き方を入れた PR #65（ブランチ `feature/issues_54-fail`、コミット `3c060ab`） | `app/routers/health.py` に、API の入力 `path` をそのまま `Path(path).read_text()` に渡す道を足した。`Analyze (python)`（run 39425694014）は成功し、`CodeQL` が `failure`（「1 new alert including 1 high severity security vulnerability」）、アラート #10 `py/path-injection`（重大度 error、セキュリティの重大度 high）が 22 行目に出た。`ci` は成功。マージせずに閉じ、ブランチは残した |
| 4 | 初回の既存の指摘 | 0 件（シナリオ 2）。直すものも、閉じるものもなかった |
| 6 | PR #64 のマージ後の main への push の実行（コミット `74c7716`） | CodeQL（run 39430900751）が成功。main（`refs/heads/main`）に 2 つの category の解析ができ、指摘は 0 件。main の CodeQL のアラート（`state=open`）は 0 件 |
| 7 | 同じ push の Scorecard の実行（run 39430900807） | SAST が 0 から 7 点に（`docs/scorecard.md` の「設定後の点（SAST）」） |

- PR #65 のアラート #10 は PR の ref（`refs/pull/65/merge`）にだけ付き、main のアラート（`state=open`）は 0 件のまま。
- 人間が Security タブ（Code scanning）で、ツール CodeQL の結果が出ていることを見る（AI は画面を見られない）。
- リポジトリを private に戻すと、GitHub Code Security のライセンスがないと CodeQL は動かない（spec 11 章）。

## 脆弱性の報告の窓口（Issue #55）

設定した日：2026-10-20。人間が設定画面（Settings → Code security →「Advanced Security」の Private vulnerability reporting の Enable）で有効にし、AI が `gh api` で読んで確かめた。窓口の案内はリポジトリの直下の `SECURITY.md`。

たとえると、工場の入口の「不具合を見つけた方へ」の掲示（`SECURITY.md`）と、鍵のかかった投書箱（非公開の脆弱性報告）。投書は持ち主と管理者だけが読める。

| 項目 | 値 | 確かめ方 |
|---|---|---|
| 非公開の脆弱性報告 | `{"enabled": true}` | `gh api repos/.../private-vulnerability-reporting`（設定の前は `false`） |
| CodeQL の default setup | `not-configured` のまま | `gh api repos/.../code-scanning/default-setup`（同じ画面の別のボタンを押していないことの確認。#54 のワークフローとぶつかるため） |
| secret scanning・Push protection | `enabled` のまま | `gh api repos/...` の `security_and_analysis` |
| Security タブの Overview | Private vulnerability reporting「Enabled」、Security policy「Disabled」 | 人間のスクリーンショット。Security policy は、`SECURITY.md` が main に入る前なので Disabled（マージ後に GraphQL で確かめる） |
| 通知（Watch） | Custom で「Security alerts」だけにチェック | 人間のスクリーンショット（Apply の前の画面）と、人間の「出来ました」。AI は `gh` のトークンに `notifications` の権限がないので読めない |

- 報告が来たとき管理者に通知が届くのは、リポジトリを「All activity」で watch しているか、「Security alerts」を購読しているとき（GitHub の公式の文書の原文を `github/docs` から取得して読んだ）。
- 報告する人の画面（Report a vulnerability のフォーム）は確かめていない。持ち主が開くと持ち主の画面になるため。有効になっていることは、上の `gh api` と Overview で確かめた。
- 報告が来たら、Security タブの Advisories で非公開のまま扱う。内容を dev-log・Issue・コミットに書かない。
- マージ後（PR #67、コミット `24558a7`）に GraphQL の `repository { isSecurityPolicyEnabled securityPolicyUrl }` が `true`・`https://github.com/Yusukeeeee7/cloud-weather/security/policy` になった（設定の前は `false`・`null`）。Scorecard の Security-Policy は 0 から 10 点（`docs/scorecard.md`）。
- 止めるときは、同じ画面の Disable を押す。`SECURITY.md` の案内と食い違うので、止めるなら `SECURITY.md` も直す。
