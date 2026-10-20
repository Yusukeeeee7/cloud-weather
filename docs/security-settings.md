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
- 同じ画面の CodeQL analysis は未設定（#18 で「公開するときに入れる」と決めたもの。別の Issue で扱う）。

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
