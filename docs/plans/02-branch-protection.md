# 計画：#2 CI の残り main のブランチ保護（Rulesets）（Issue #53）

状態：承認済み（2026-10-20。質問 1〜8 はすべて「おすすめ」で決定）

## 目的と受け入れ条件

spec 14 章 #2 の行（引用）：

> | 2 | CI | PR で ci.yml が実行され、失敗時に PR がマージできない | 進行中（ci.yml 導入済み。PR での実行確認とブランチ保護の設定が残っている） |

Issue #53 の本文（引用）：

> Scorecard の Branch-Protection が 0 点（#24、`docs/scorecard.md`）。main に Rulesets を設定する（force push・削除の禁止、CI の成功を必須に）。spec #2 の「ブランチ保護の設定が残っている」と同じ作業。承認の必須は 1 人の開発なので入れない（Code-Review は直さないと決めた）。

この Issue での受け入れ条件（上の 2 つから）：

1. main に Rulesets が 1 つあり、有効（Active）になっている。
2. main の force push と削除が禁止されている。
3. `ci`（`ci.yml` のジョブ）が成功していない PR は、main にマージできない。これを、わざと失敗させた PR で 1 回確かめる。
4. 設定の内容と確かめた結果を docs に記録する。

「PR での実行確認」は、#3 以降のすべての PR で `ci` が動いているので済んでいる（例：PR #60 の check run `ci`）。

## いまの状態（2026-10-20、AI が `gh api` で確認）

| 項目 | 結果 |
|---|---|
| リポジトリの公開 | public |
| Rulesets（`GET repos/.../rulesets`） | なし（空の配列） |
| クラシックのブランチ保護（`GET .../branches/main/protection`） | なし（404「Branch not protected」） |
| main に効いているルール（`GET .../rules/branches/main`） | なし（空の配列） |
| CI の check run の名前 | `ci`（アプリ `github-actions`）。`ci.yml` のきっかけは `pull_request` だけで、パスの絞り込みはない |

## Scorecard の採点（公式の `docs/checks.md` の Branch-Protection の節。2026-10-20 に `gh api` で取得して読んだ）

段（Tier）ごとの採点で、前の段をすべて満たさないと次の段の点は入らない（段の中は部分点あり）。

| 段 | 点 | 条件 |
|---|---|---|
| 1 | 3/10 | force push の禁止、削除の禁止 |
| 2 | 6/10 | 承認 1 人以上、（管理者）PR を必須、（管理者）最新の main の取り込み、（管理者）最後の push の承認 |
| 3 | 8/10 | 1 つ以上のステータスチェックを必須 |
| 4・5 | 9・10 | 承認 2 人、コードオーナー、古い承認の取り消しなど |

- 既定の `GITHUB_TOKEN`（管理者の権限なし）で実行すると、「管理者」と付いた条件は満たしたものとして数える（同じ節の Note）。
- 承認の必須は入れない（Issue の本文）ので、段 2 を満たせない。**見込みは 3 点以上 6 点未満**。CI の必須（段 3）は点には入らないが、spec #2 の受け入れ条件なので入れる。実際の点は、マージ後の Scorecard の実行で確かめて記録する（AI が点を予想で書かない）。
- Rulesets にバイパス（例外として通せる人）を 1 つでも足すと、Scorecard は「管理者にも適用」を false と数える。

## 設定する Ruleset（案）

たとえると、工場の出荷口（main）に門番を置く。門番は「検品係（CI）の合格札がない箱は通さない」「出荷口を壊さない・出荷済みの箱をすり替えない」を守らせる。持ち主（管理者）も例外にしない。

| 画面の項目 | 値 | 理由 |
|---|---|---|
| 名前 | `main` | |
| Enforcement status | Active | |
| Bypass list | なし（管理者も例外にしない） | #2 の決定（2026-10-12「管理者にも適用」）。Scorecard の数え方とも合う（質問 3） |
| Target branches | Include default branch | main は既定のブランチ |
| Restrict deletions | オン | Issue の本文 |
| Block force pushes | オン | Issue の本文 |
| Require a pull request before merging | オン、承認の数 0 | main への直接の push を止める。CLAUDE.md の「main への直接コミットをしない」を仕組みで守る（質問 1） |
| Require status checks to pass | オン、`ci`（GitHub Actions） | spec #2 の受け入れ条件 |
| Require branches to be up to date before merging | オフ | #2 の決定（1 人の開発で PR が並ばない。取り込みのたびに CI が 1 回動く）（質問 4） |
| そのほか（署名付きコミット、直線の履歴、デプロイの成功など） | オフ | Issue と spec にない |

画面の項目名は、設定するときに画面の表示で確かめる（上は AI の記憶による名前。違っていたら記録のときに直す）。

## 進め方（順番）

1. ブランチ `feature/issues_53` を作り、この計画をコミットして PR を出す（この PR の CI が `ci` を 1 回動かす）。
2. **人間が設定画面（Settings → Rules → Rulesets）で上の Ruleset を作る**（質問 2）。
3. AI が `gh api` で設定を読み、上の表と同じかを確かめる（シナリオ 1・2）。
4. 確認用のブランチ `feature/issues_53-fail` で、テストを 1 件わざと失敗させる PR を出し、マージできないことを確かめて、**マージせずに閉じる**（シナリオ 3）。ブランチは消さない（CLAUDE.md の「ブランチ削除をしない」）。
5. 記録（`docs/security-settings.md`・spec）をこの PR に足し、CI が成功したら人間がマージする（シナリオ 4。保護をかけたあとの最初のマージ）。
6. マージで main への push が起き、Scorecard が動く。点を `docs/scorecard.md` に記録する別の PR（`feature/issues_53-verify`）を出す（シナリオ 5、質問 7）。

## 今回やらないこと

- 承認（レビュー）の必須。1 人の開発で、自分の PR を承認できないため（Code-Review は直さないと #24 で決めた）。
- 最新の main の取り込みの必須（質問 4）。
- main への直接の push・force push・削除を実際に試すこと。設定が間違っていたら main の履歴が変わってしまうため。`gh api` で効いているルールを読んで確かめる（質問 6）。
- クラシックのブランチ保護。Rulesets にする（Scorecard が既定のトークンで読めるのは Rulesets。#24 の質問 3 の回答）。
- マージの方法（merge・squash・rebase）の制限、マージ後のブランチの自動削除。
- `ci.yml` の変更。ジョブの名前 `ci` を変えると必須チェックが見つからずマージできなくなるので、変えない。
- CodeQL（#54）・SECURITY.md（#55）・ライセンス（#56）。

## 変更・追加するファイル

| ファイル | 内容 |
|---|---|
| `docs/plans/02-branch-protection.md` | この計画 |
| `docs/security-settings.md` | 節「main のブランチ保護（#2、Issue #53）」を足す。Ruleset の設定（`gh api` の結果から作った表）、確かめた日、シナリオ 1〜4 の結果、CI が壊れてマージできなくなったときの戻し方（人間が Ruleset を一時的に Disabled にして直し、Active に戻す） |
| `docs/spec.md` | 14 章の #2 の状態を「完了」に（シナリオ 3 が通ったとき）。11 章または 13 章に「main は Rulesets で保護」の 1 行（どちらに置くかは実装時に、既存の書き方に合わせる） |
| `docs/scorecard.md` | 別の PR（手順 6）：「点の低い項目への対応」の Branch-Protection の行に、設定後の点と実行の番号を書く |
| `docs/dev-log.md` | `/dev-log` で記録 |
| （確認用、マージしない）`tests/` のどれか 1 ファイル | `feature/issues_53-fail` だけで、必ず失敗する 1 件を足す。main には入らない |

コードとテストの変更はない（main に入るのは docs だけ）。テストの影響を検索した結果：`ci` というジョブ名・Rulesets を参照するテストはない（設定は GitHub 側にある）。

## テスト一覧（確かめる順）

この機能は GitHub の設定なので、pytest のテストではなく、確かめのシナリオにする。TDD の「Red」にあたるのはシナリオ 3（失敗する PR が止められる）。

| # | シナリオ | 種類 | 確かめること |
|---|---|---|---|
| 0 | 設定の前に `GET repos/.../rules/branches/main` | 異常（Red） | 空の配列（いまは何も効いていない）。設定前の状態の記録 |
| 1 | `GET repos/.../rulesets` と `GET repos/.../rulesets/<id>` | 正常 | Ruleset が 1 つ、`enforcement` が active、対象が既定のブランチ、バイパスが空。ルールが削除の禁止・force push の禁止・PR の必須（承認 0）・ステータスチェック `ci` の 4 つ。最新の取り込みはオフ |
| 2 | `GET repos/.../rules/branches/main` | 正常 | シナリオ 1 の 4 つのルールが main に効いている |
| 3 | 確認用 PR（テストを 1 件わざと失敗）| 異常 | `ci` が失敗し、`gh pr view --json mergeStateStatus` が `BLOCKED`。人間が画面でマージのボタンが押せないことを見る。マージせずに閉じる |
| 4 | この PR（docs だけ）| 正常（Red にならない。いまの動作を守る） | `ci` が成功すると `mergeStateStatus` が `CLEAN` になり、人間がマージできる |
| 5 | マージ後の Scorecard の実行（main への push）| 結果で中身が変わる（Red にならない） | 実行が成功し、Branch-Protection が 0 より上になる。点と理由を `api.scorecard.dev` の JSON から写さずに表にして記録する。見込み（3〜6 未満）と違ったら、理由を Scorecard の出力から読んで書く |

## 追加する依存パッケージ

なし

## セキュリティ上の注意

- 入力検証：該当なし（API のコードは変えない）。
- シークレット：使わない。PAT は作らない（Scorecard は既定のトークンで Rulesets を読める）。`gh` のトークンを出力やログに出さない。
- 外部通信（ホスト・タイムアウト）：`api.github.com`（`gh api` の GET だけ。設定の書き込みは人間が画面でする）、`api.scorecard.dev`（結果の JSON を読む）。アプリの通信先は変わらない。
- 保護の穴：バイパスを足さない。Rulesets を Disabled にすると保護が外れるので、戻し方を docs に書き、外したら Active に戻したことを `gh api` で確かめる。

## リスク・未決事項

- **CI が止まる・壊れると、誰もマージできなくなる。** 管理者も例外にしないため。直し方は、人間が Ruleset を一時的に Disabled にして直し、Active に戻す（#2 の決定どおり）。
- **`ci` が `cancelled` になるとマージできない。** `ci.yml` は同じ PR の古い実行を止める（`cancel-in-progress: true`）。PR #60 の最後の `ci` も `CANCELLED` だった。新しい push があれば新しい実行が成功すればよいが、最後の実行が止まったままなら、`gh run rerun` か画面で再実行する。
- **Dependabot の PR も `ci` の成功が必要になる。** いまも CI は動いているので、動きは変わらない。
- **必須チェックの名前は `ci` に結びつく。** あとでジョブの名前を変えるときは、Ruleset も同時に変える（#2 の計画のリスクと同じ）。
- **画面の項目名は AI の記憶。** 設定のときに画面で確かめ、記録は `gh api` の結果から作る。
- Scorecard の点は見込み（3 以上 6 未満）で、確かめるまで分からない。

## ブロッカー（人間の対応が必要なこと）

- Ruleset の作成（手順 2）。AI は設定を書き込まない（質問 2）。
- シナリオ 3・4 の画面での確認（マージのボタン）と、この PR のマージ。
- 外部 API の表（spec 7 章）の項目は使わない。ブロッカーなし。

## 質問

1. **「PR を必須（承認 0）」も入れてよいか。** Issue の本文にはない。入れると、main への直接の push（自分のものも）が止まる。CD・Scorecard は main に push しないので影響はない。（おすすめ：入れる。CLAUDE.md の「main への直接コミットをしない」を、運用ではなく仕組みで守れる。承認 0 なので自分でマージできる）
2. **誰が Ruleset を作るか。**（おすすめ：人間が設定画面で作り、AI が `gh api` の GET で確かめて記録する。#19 の secret scanning と同じ分担。AI が `gh api` で書き込む案は、送る JSON の項目名を公式ドキュメントで確かめる手間があり、リポジトリの設定を AI が変えることになる）
3. **バイパスを置かない（管理者にも適用）でよいか。**（おすすめ：置かない。#2 で決めたとおりで、Scorecard もバイパスがあると「管理者に適用していない」と数える。困ったときは Ruleset を一時的に Disabled にする）
4. **「最新の main の取り込み」を必須にしないでよいか。**（おすすめ：しない。#2 の決定のまま。既定のトークンでは、この条件は点に影響しない）
5. **わざと失敗させる確認用の PR を作り、マージせずに閉じてよいか。** ブランチ `feature/issues_53-fail` は消さずに残す。（おすすめ：作る。spec #2 の「失敗時に PR がマージできない」を確かめる唯一の方法で、#2 の計画のシナリオ 4 の積み残し）
6. **直接の push・force push・削除の拒否を、実際に試さなくてよいか。**（おすすめ：試さない。設定が間違っていたら main が書き換わる。`gh api` で効いているルールを読むことで代える）
7. **Scorecard の点の記録は、マージ後の別の PR（`feature/issues_53-verify`）にしてよいか。**（おすすめ：別の PR。点はマージ後の実行でしか分からず、#52 の `-verify` と同じ形）
8. **spec #2 の状態は、シナリオ 3 が通ったら「完了」にしてよいか。**（おすすめ：する。受け入れ条件の「PR で ci.yml が実行され」「失敗時に PR がマージできない」の両方がそろう）
