# 計画：#24 Scorecard の残り SECURITY.md（脆弱性の報告の窓口）（Issue #55）

状態：承認済み（2026-10-20、人間の回答「全部おすすめで進めてください」。質問 1〜7 はすべて「おすすめ」で決定）

## 目的と受け入れ条件

Issue #55 の本文（引用）：

> Scorecard の Security-Policy が 0 点（#24、`docs/scorecard.md`）。`SECURITY.md` を置き、脆弱性の報告の窓口を書く（GitHub の非公開の脆弱性報告を使う予定。設定は人間が画面で確かめる）。

`docs/scorecard.md`「点の低い項目への対応」の Security-Policy の行（引用）：

> | Security-Policy | 0 | 直す（別の Issue） | `SECURITY.md` を置き、脆弱性の報告の窓口を書く（GitHub の非公開の脆弱性報告を使う予定。設定は Issue で確かめる） |

spec 14 章には、この作業の行がない。Scorecard（#24）で決めた「点の低い項目を直す」の 1 つとして扱う（質問 1）。

この Issue での受け入れ条件（上から）：

1. リポジトリの直下に `SECURITY.md` があり、脆弱性の報告の窓口（GitHub の非公開の脆弱性報告）と、報告してほしいこと・対象・返事の目安が書いてある。
2. GitHub の非公開の脆弱性報告（Private vulnerability reporting）が有効になっている。
3. GitHub がこのファイルをセキュリティポリシーとして認識している。
4. 設定と結果を docs に記録し、マージ後の Scorecard の Security-Policy の点を記録する。

たとえ：工場の入口に「不具合を見つけた方へ」という掲示を貼り、通りに面した掲示板（Issue）ではなく、鍵のかかった投書箱（非公開の脆弱性報告）に入れてもらうよう案内する。投書箱は、持ち主と管理者だけが開けられる。

## 調べたこと（2026-10-20、AI が `gh api` で確認）

**リポジトリの状態**

| 項目 | 結果 |
|---|---|
| `SECURITY.md` | なし（直下・`.github/`・`docs/` のどれにもない） |
| 非公開の脆弱性報告（`GET repos/.../private-vulnerability-reporting`） | `{"enabled": false}` |
| GitHub の認識（GraphQL の `repository { isSecurityPolicyEnabled securityPolicyUrl }`） | `false`・`null` |
| README | なし（リポジトリの直下にない） |
| 公開 | public（非公開の脆弱性報告は public のリポジトリで使える。下の公式の文書） |

**Scorecard の Security-Policy の採点**（`ossf/scorecard` の `docs/checks.md` と、v5.6.0 のソース `checks/evaluation/security_policy.go`・`checks/raw/security_policy.go`・`probes/securityPolicyContains*` を `gh api` で取得して読んだ）：

| 条件 | 点 | ソースでの見方 |
|---|---|---|
| ファイルがある | 0（ないと全体が 0） | 名前が `SECURITY.md`（大文字小文字は問わない）で、直下・`.github/`・`docs/` のどこか（`.markdown`・`.adoc`・`.rst` も可） |
| リンク | 6 | `http://`・`https://` の URL か、メールアドレスが 1 つ以上 |
| リンク以外の文章 | 3 | ファイルの大きさが、URL・メールの文字数（＋ 1 つにつき 2）より大きい |
| 脆弱性・開示・日数の言葉 | 1 | 行ごとに `Vuln`・`Disclos`（大文字小文字は問わない）か、1〜4 桁の数字を数え、合計が 2 以上 |

- 合計の見込みは 10 点（質問 3 のおすすめの書き方の場合）。実際の点はマージ後の Scorecard の実行で確かめて記録する（AI が点を予想で書かない）。
- メールアドレスは要らない（URL だけで 6 点）。

**GitHub の公式の文書**（`github/docs` のリポジトリから原文を `gh api` で取得して読んだ）：

- `configure-vulnerability-reporting/add-security-policy.md`：`SECURITY.md` に、対象の版と脆弱性の報告の仕方を書く。
- `configure-vulnerability-reporting/configure-for-a-repository.md`：有効にするのは、リポジトリの Settings →（サイドバーの）Code security →「Advanced Security」の下の「Private vulnerability reporting」の右の **Enable**。public のリポジトリの持ち主と管理者ができる。
- `reusables/security-advisory/private-vulnerability-reporting-security-researcher.md`：有効にすると、報告する人には、リポジトリの「Advisories」のページに **Report a vulnerability** のボタンが出る。
- `reusables/security-advisory/private-vulnerability-reporting-configure-notifications.md`：報告が来たとき、管理者に通知が届くのは、リポジトリを「All activity」で watch しているか「Security alerts」を購読していて、かつリポジトリの通知が有効なとき。
- 報告のフォームは `.github/VULNERABILITY_REPORT.yml` で変えられる（今回はやらない）。

**報告の URL**：`https://github.com/Yusukeeeee7/cloud-weather/security/advisories/new`。いまはログインしていない `curl` で 302（転送）、`.../security/advisories` は 200。この URL の形は公式の文書の原文には出てこない（文書は「Advisories のページのボタン」とだけ書く）。有効にした後、人間がブラウザでこの URL を開き、報告のフォームが出ることを確かめる（シナリオ 3）。

## 進め方（順番）

1. ブランチ `feature/issues_55` で `SECURITY.md` と計画をコミットして PR を出す。
2. **人間が設定画面で、非公開の脆弱性報告を有効にする**（質問 4）。
3. AI が `gh api` で有効になったことを読んで確かめる（シナリオ 2）。人間がブラウザで報告の URL を開く（シナリオ 3）。
4. 記録（`docs/security-settings.md`・spec）を同じ PR に足し、人間がマージする。
5. マージ後、AI が GraphQL で GitHub の認識を確かめる（シナリオ 4。既定のブランチに入ってから認識されるため）。Scorecard の点を記録する別の PR（`feature/issues_55-verify`）を出す。**`Closes #55` はこの最後の PR に付ける**（質問 6）。

## 人間にお願いする設定（手順 2）

| 項目 | 内容 |
|---|---|
| 場所 | リポジトリの Settings →（左のサイドバー）Code security →「Advanced Security」の下の「Private vulnerability reporting」 |
| 操作 | 右の **Enable** を押す |
| 間違えやすいこと | 同じ画面に Enable のボタンが並んでいる。**「CodeQL analysis」の default setup を有効にしない**（#54 のワークフロー `codeql.yml` と同時には使えない。default setup を有効にすると、ワークフローの解析の結果の送信が断られる見込み（確かめていない））。Dependabot の項目なども押さない |
| 設定後に AI が読む値 | `GET repos/Yusukeeeee7/cloud-weather/private-vulnerability-reporting` が `{"enabled": true}`。`GET .../code-scanning/default-setup` の `state` が `not-configured` のまま（ほかのボタンを押していないことの確認） |
| 通知 | 報告が来たときに気づけるよう、リポジトリの Watch が「All activity」か、「Custom」で「Security alerts」になっているかを見る（公式の文書の通知の条件）。AI は API で確かめられないので、人間が画面で見て教えてほしい |

## 今回やらないこと

- 報告のフォームの変更（`.github/VULNERABILITY_REPORT.yml`）。
- メールアドレスの公開（窓口は非公開の脆弱性報告だけにする。質問 2）。
- 試しの報告を送ること（自分のリポジトリへの報告は、実際の報告と区別がつかなくなる。報告のフォームが出ることだけを確かめる）。
- ライセンス（#56）、README の作成。
- アプリのコード・テスト・ワークフローの変更。

## 変更・追加するファイル

| ファイル | 内容 |
|---|---|
| `SECURITY.md` | 新規（リポジトリの直下）。下の「SECURITY.md の中身（案）」 |
| `docs/plans/24-security-policy.md` | この計画 |
| `docs/security-settings.md` | 節「脆弱性の報告の窓口（Issue #55）」を足す。非公開の脆弱性報告の設定（`gh api` の結果）、確かめた日、シナリオの結果、通知の設定（人間が画面で見た結果） |
| `docs/spec.md` | 11 章（セキュリティ要件）に「脆弱性の報告の窓口：`SECURITY.md` と非公開の脆弱性報告」の 1 行。14 章には行を足さない（質問 1） |
| `docs/scorecard.md` | 別の PR（手順 5）：Security-Policy の行と、設定後の点 |
| `docs/dev-log.md` | `/dev-log` で記録（#54 の記録の追記と、`.claude/skills/implement-feature/SKILL.md` の変更も、この Issue のブランチで一緒にコミットする（#54 の `/dev-log` で人間が決めた）） |

テストへの影響を検索した結果：`SECURITY`・`security.md`・`advisories` を参照するテストはない（実装時に `grep` で確かめる）。

## SECURITY.md の中身（案）

日本語を先に、短い英語を後に置く（質問 3）。

1. **対象**：このリポジトリのコード（API・画面・ノートブック・ワークフロー・Dockerfile）と、CD が ghcr.io に push するイメージの最新（`latest`）。古いイメージ・過去のコミットは直さない。
2. **報告の仕方**：公開の Issue・PR・Discussions に書かない。リポジトリの Security タブ →「Report a vulnerability」（`https://github.com/Yusukeeeee7/cloud-weather/security/advisories/new`）から、非公開で報告する。
3. **書いてほしいこと**：どこで（ファイル・エンドポイント）、再現の手順、影響。
4. **対象外**：外部のサービス（Open-Meteo、IEM の METAR）や依存パッケージそのものの脆弱性は、それぞれの提供元へ。このリポジトリでの使い方の問題は対象。
5. **返事の目安**（質問 5）：個人の学習用のリポジトリで、1 人で見ている。受け取りの返事は 7 日以内、直すか判断を伝えるのは 30 日以内を目安にする。公開（開示）は、直した後に、報告した人と相談して GitHub の Security Advisory で行う。
6. **English**：上の 2・5 を短く（「Please do not open a public issue. Report vulnerabilities privately via ... We aim to respond within 7 days.」）。

- 本物のシークレット・メールアドレスは書かない。
- 数字（7・30）と「Vulnerability」「disclosure」は、Scorecard の 1 点の条件にも当たる（点のためではなく、返事の目安として書く）。

## テスト一覧（確かめる順）

この機能は文書と GitHub の設定なので、pytest のテストではなく、確かめのシナリオにする。TDD の「Red」にあたるのはシナリオ 0。

| # | シナリオ | 種類 | 確かめること |
|---|---|---|---|
| 0 | 設定の前に `GET .../private-vulnerability-reporting`、GraphQL の `isSecurityPolicyEnabled` | 異常（Red） | `enabled: false`、`isSecurityPolicyEnabled: false`。設定前の記録 |
| 1 | `SECURITY.md` を Scorecard の決まりで読む（作業用の短いスクリプトで、ソースの正規表現と同じ数え方をする。リポジトリには入れない） | 正常 | URL が 1 つ以上、URL 以外の文章がある、`Vuln`・`Disclos`・数字の合計が 2 以上。シークレット・メールアドレスがない（gitleaks も CI で見る） |
| 2 | 人間が有効にした後、`GET .../private-vulnerability-reporting`・`GET .../code-scanning/default-setup` | 正常 | `enabled: true`。default setup は `not-configured` のまま |
| 3 | 人間がブラウザで報告の URL を開く | 正常 | 報告のフォーム（Summary など）が出る。送信はしない |
| 4 | マージ後、GraphQL の `isSecurityPolicyEnabled`・`securityPolicyUrl` | 正常 | `true`、URL が `SECURITY.md` を指す |
| 5 | マージ後の Scorecard の実行 | 結果で中身が変わる（Red にならない） | Security-Policy が 0 より上になる。点・理由・details を `api.scorecard.dev` の JSON から写して記録する。見込み（10）と違ったら、理由を出力から読んで書く |
| 6 | 既存の全テスト・ruff・mypy（PR の CI） | 正常（Red にならない。いまの動作を守る） | コードを変えていないので、すべて通る |

## 追加する依存パッケージ

なし

## セキュリティ上の注意

- 入力検証：該当なし（アプリのコードは変えない）。
- シークレット：使わない。`SECURITY.md` にメールアドレス・個人の情報を書かない（窓口は GitHub の非公開の報告だけ）。
- 外部通信：`api.github.com`（`gh api` の GET と GraphQL の読み取りだけ。設定の書き込みは人間が画面でする）、`github.com`（報告のページの確認）、`api.scorecard.dev`（結果の JSON を読む）。アプリの通信先は変わらない。
- 報告が来たら：Security タブの Advisories で非公開のまま扱う。内容を dev-log・Issue・コミットに書かない。

## リスク・未決事項

- **通知に気づけないと、窓口があっても返事ができない。** 通知の条件（watch・Security alerts）を人間が画面で見る。
- **返事の目安を守れないとき**：個人の学習用なので、目安であることを書く。目安の日数は持ち主が決める（質問 5）。
- **報告の URL の形**（`/security/advisories/new`）は公式の文書の原文にない。シナリオ 3 で人間が確かめ、違ったら直す。
- **default setup の誤操作**：同じ画面の CodeQL の Enable を押すと、#54 のワークフローとぶつかる見込み。シナリオ 2 で `not-configured` のままかを読む。
- Scorecard の点は見込み（10）で、確かめるまで分からない。

## ブロッカー（人間の対応が必要なこと）

- 非公開の脆弱性報告の有効化（手順 2）。AI は設定を書き込まない。
- 報告のフォームが出ることの確認（シナリオ 3）と、通知の設定の確認。
- この PR と `-verify` の PR のマージ。
- spec 7 章の外部 API の項目は使わない。ブロッカーなし。

## 質問

未回答：なし

回答済み（2026-10-20、人間の回答「全部おすすめで進めてください」）：#24 の残りとして扱い spec は 11 章に 1 行、窓口は非公開の脆弱性報告だけ（メールなし）、日本語を先に短い英語を後に、有効化は人間が画面で AI が GET で確かめる、返事の目安は 7 日・30 日、点の記録は `-verify` の PR で `Closes #55` もそこに付ける、#54 の dev-log と skill の変更は別のコミットにする。

以下は、レビューのときに示した質問の原文。

1. **spec のどの機能として扱うか。** spec 14 章に、この作業の行がない。（おすすめ：#24（Scorecard）の「点の低い項目を直す」の 1 つとして扱い、計画を `24-security-policy.md` にする。spec には 11 章に 1 行足すだけにし、14 章に行は足さない。#53 は #2、#54 は #18 に当てはまる行があったが、今回はないため）
2. **窓口**：（おすすめ：GitHub の非公開の脆弱性報告だけ。メールアドレスは公開しない。Scorecard も URL だけで 6 点になる）
3. **言語**：（おすすめ：日本語を先に、短い英語を後に。docs はすべて日本語だが、public のリポジトリで、報告する人が日本語を読めるとは限らない）
4. **誰が有効にするか**：（おすすめ：人間が設定画面で有効にし、AI が `gh api` の GET で確かめる。#19・#53 と同じ分担。AI が API（PUT）で有効にする案は、リポジトリの設定を AI が変えることになる）
5. **返事の目安の日数**：（おすすめ：受け取りの返事は 7 日以内、判断を伝えるのは 30 日以内、を「目安」として書く。日数は持ち主が守れる数にしてほしいので、変えたければ教えてほしい）
6. **Scorecard の点の記録は、マージ後の別の PR（`feature/issues_55-verify`）にし、`Closes #55` をその PR に付けてよいか。**（おすすめ：そうする。#53・#54 と同じ形）
7. **#54 の dev-log の追記と skill の変更を、この Issue のブランチで一緒にコミットしてよいか。** #54 の `/dev-log` で「次の Issue に混ぜる」と決めた。（おすすめ：最初のコミットとは分けて、別のコミット（`docs: #54 の dev-log と implement-feature の変更`）にする。PR の本文にも書く）

## 実装時の変更

- **#54 の記録の別のコミット**（質問 7）：`948c05b`（#54 の dev-log と `implement-feature` の変更）。この Issue の `SECURITY.md` は `920a3e4`。
- **シナリオ 1 の数え方のスクリプト**：作業用のフォルダに置き、リポジトリには入れていない。Go の `\b*` は Python では `(?:\b)*` と書いた。結果：URL 2 つ、メール 0、`Vuln`・`Disclos`・数字の合計 15、見込み 10 点。わざと壊した 3 通り（URL を消す → 4 点で FAIL、メールを足す → FAIL、URL だけ → 6 点で FAIL）を検出した。
- **シナリオ 3 は計画どおりにできなかった**：人間が送ったのは報告のフォームではなく、Security タブの Overview（Private vulnerability reporting が Enabled）。持ち主が報告の URL を開くと、持ち主の画面になる可能性があり（確かめていない）、報告する人の画面は持ち主からは見られない。Overview と `gh api` で代え、`docs/security-settings.md` にそう書いた。
- **通知**（計画の「人間にお願いする設定」）：`gh api repos/.../subscription` は、トークンに `notifications` の権限がなく読めなかった（権限は足していない）。人間が Watch を Custom の「Security alerts」だけにした（スクリーンショット）。
