# 計画：#20 ワークフロー・Dockerfile の検査（Issue #39）

状態：承認済み（2026-10-16、人間の回答「おすすめで進めてください」）

## 目的と受け入れ条件

spec.md「14. 機能一覧」より：

> | 20 | ワークフロー・Dockerfile の検査 | CI で zizmor・actionlint（`.github/workflows/`）と hadolint（`Dockerfile`・`Dockerfile.dev`）が実行され、指摘があれば失敗する。既存の指摘は直すか、理由を書いて 1 件ずつ除外する | 未着手 |

spec.md「11. セキュリティ要件」の共通の決まりより：

> - ツール・Action を足すときは、計画に理由を書いて承認を得る。Action はほかと同じくコミットの SHA で固定する。
> - ツールの設定・引数・出力の形式は推測で書かない。公式ドキュメントで確かめ、確かめたことを計画に書く。
> - 検査で見つかった既存の指摘は、直すか、理由をコメントに書いて 1 件ずつ除外する。ルールや検査をまとめて外して通さない。
> - 検査が外部と通信するもの（脆弱性のデータベースの取得など）は、通信先を計画に書く。

たとえ：工場の「作業手順書の検品係」。製品（アプリのコード）ではなく、**製品を作る手順書**を見る。

| 係 | 見る手順書 | 何を見るか |
|---|---|---|
| actionlint | ワークフロー（`.github/workflows/`） | 書き方の間違い（存在しない項目、式の型、`run:` のシェルの誤り。shellcheck を中に持つ） |
| zizmor | ワークフロー（`.github/workflows/`） | セキュリティの穴（外から入る文字列をそのままシェルに渡す、権限が広すぎる、Action を版の名前だけで固定、など） |
| hadolint | `Dockerfile`・`Dockerfile.dev` | イメージの作り方の悪い癖（`latest` を使う、root で動かす、など） |

## 調べたこと（2026-10-16）

**公式ドキュメント**（どれも WebFetch の要約で読んだ。原文は読んでいない）：

- **zizmor**（`docs.zizmor.sh` の Usage・Installation）
  - 公式の Docker イメージ：`ghcr.io/zizmorcore/zizmor`。
  - 終了コード：0 は指摘なし、1 はエラー、2 は引数の誤り、3 は入力が 1 つもない、**11〜14 は指摘あり**（いちばん重い指摘が 11 informational・12 low・13 medium・14 high）。
  - `GH_TOKEN`・`GITHUB_TOKEN`・`ZIZMOR_GITHUB_TOKEN` のどれもなければ offline で動く。`--offline` で明示できる。online のときは GitHub の API を使う監査（Action の既知の脆弱性など）も動く。
  - `--persona`：`regular`（既定）・`pedantic`・`auditor`（誤検知もすべて出す）。
  - 除外：対象の行の上の YAML のコメント `# zizmor: ignore[ルール名]`、または `zizmor.yml` の `rules: <ルール名>: ignore: - ファイル:行`。
- **actionlint**（`github.com/rhysd/actionlint` の `docs/usage.md`・`docs/config.md`）
  - 公式の Docker イメージ：`rhysd/actionlint`。**shellcheck と pyflakes が入っている**。
  - 終了コード：0 は問題なし、1 は問題あり、2 は引数の誤り、3 は致命的なエラー。
  - 除外：`-ignore '<正規表現>'`、または `.github/actionlint.yaml` の `paths: <glob>: ignore: [<正規表現>]`。`# shellcheck disable=` が効くかは、読んだページに書かれていなかった。
  - 実行のときに通信が要るかは書かれていなかった（下の「手元で実行して確かめたこと」で `--network none` で動いた）。
- **hadolint**（`github.com/hadolint/hadolint` の README）
  - 公式の Docker イメージ：`hadolint/hadolint`・`ghcr.io/hadolint/hadolint`。例：`docker run --rm -i hadolint/hadolint < Dockerfile`。
  - `--failure-threshold`（`-t`）の既定は `info`（info 以上の指摘で失敗）。終了コードの数値は README に書かれていない。
  - 除外：その命令の直前の行に `# hadolint ignore=DL3008 # 理由`（次の 1 命令だけに効く。理由は `#` をもう 1 つ付けて書く）。ファイル全体の `# hadolint global ignore=` と `.hadolint.yaml` の `ignored:` もある（**使わない**。まとめて外すことになる）。
  - DL3006：イメージのタグを明示する。DL3007：`latest` を使わない。DL3008：`apt-get install` の版を固定する。

**手元で実行して確かめたこと**（`:latest` のイメージを Docker Desktop で `--network none` で実行。ファイルは変えていない）：

| ツール（版） | 対象 | 結果 |
|---|---|---|
| hadolint 2.15.1 | `Dockerfile` | **2 件**：20 行目 DL3008（warning、`libgomp1` の版を固定していない）、35 行目 DL3066（info、`USER appuser` が数字でない）。終了コード 1 |
| hadolint 2.15.1 | `Dockerfile.dev` | **2 件**：14 行目 DL3008、29 行目 DL3066。終了コード 1 |
| actionlint 1.7.12 | `.github/workflows/` | 指摘なし。終了コード 0 |
| zizmor v1.31.1（offline、regular） | `.github/workflows/` | 指摘なし（`3 suppressed`）。終了コード 0 |
| zizmor（offline、auditor） | `.github/workflows/` | 3 件（上の `3 suppressed` の中身）：`undocumented-permissions`（`cd.yml` の `packages: write` に説明のコメントがない、low）、`anonymous-definition`（ジョブに `name:` がない、2 件、informational） |
| zizmor（offline、regular） | `.github/`（`dependabot.yml` を含む） | 3 件：`dependabot-cooldown`（medium。新しい版が出てすぐに更新の PR を作る。3 つの ecosystem それぞれ） |

- DL3066 は `info` だが、既定の `--failure-threshold`（info）で失敗になる。
- いまの `:latest` の digest（実装のときに、版のタグの digest と同じかを確かめる）：
  - `hadolint/hadolint@sha256:32dac94127fd60b7b7e3fbfc65e1383b9b5e25c9bfd7b8536de7a539fe68a12d`
  - `rhysd/actionlint@sha256:b1934ee5f1c509618f2508e6eb47ee0d3520686341fec936f3b79331f9315667`
  - `ghcr.io/zizmorcore/zizmor@sha256:42d409dbb851d4c5d35a058cf042b828bea1e3f2884378c526eb0974780e18d9`

## 今回やらないこと

- #21 以降の検査（ベースイメージの digest 固定、Trivy など）
- `dependabot.yml` の検査と `cooldown` の設定（spec の対象は `.github/workflows/`。質問 3）
- zizmor の `pedantic`・`auditor` の指摘（`name:` を足すなど）。誤検知を含む前提の設定で、spec は既定で通ることを求めている（質問 2）
- zizmor の online の監査（GitHub の API と通信する。質問 4）
- pre-commit のフック（手元で止める仕組み）
- `cd.yml` に検査を足すこと（spec は `ci.yml`）

## 変更・追加するファイル

| ファイル | 内容 |
|---|---|
| `.github/workflows/ci.yml` | gitleaks の後、setup-uv の前に 3 つの手順を足す：actionlint・zizmor（`.github/workflows/`）、hadolint（`Dockerfile`・`Dockerfile.dev`）。どれも公式の Docker イメージを **版のタグ + digest** で固定し、`docker run --rm --network none` で、リポジトリを読み取り専用（`:ro`）で載せて実行する |
| `Dockerfile` | DL3066：`USER appuser` → `USER 10001`（直す）。DL3008：`# hadolint ignore=DL3008 # 理由` を 1 か所（質問 1） |
| `Dockerfile.dev` | 同じく 2 か所 |
| `docs/spec.md` | #20 の状態、「13. CI/CD」の `ci.yml` の内容に 3 つの検査を足す |

- 手順の順番：gitleaks（シークレットを先に止める）→ actionlint → zizmor → hadolint → これまでの手順。3 つとも数秒で終わり、依存のインストールが要らないので前に置く。
- `docker run` のイメージなので、**Dependabot はこれらの行を更新しない**（gitleaks・uv の行と同じ。コメントにそう書く）。
- `USER 10001`：`useradd --uid 10001 appuser` で作ったユーザーと同じ uid。`chown -R appuser /venv`（`Dockerfile.dev`）と、コメントの「appuser は読むだけ」はそのまま。数字にしても、動くユーザーは変わらない（テスト 9 で確かめる）。

## テスト一覧（先に書く順）

3 つのツールは pytest の対象にならない。ツールを実行して確かめる（#19 と同じやり方）。

| # | 確認 | 種類（正常/異常/境界） | 確かめること |
|---|---|---|---|
| 1 | 作業用フォルダ（scratchpad）に**わざと悪いワークフロー**（`run:` に `${{ github.event.pull_request.title }}` をそのまま書く）を置き、CI と同じイメージ・引数で zizmor を実行 | 異常 | 終了コード 11 以上で失敗する（`template-injection`。**Red**：検査係が本当に見ていること） |
| 2 | 作業用フォルダに**書き方の誤ったワークフロー**（存在しない項目・`run:` の中の shellcheck に当たる書き方）を置き、actionlint を実行 | 異常 | 終了コード 1 で失敗する。shellcheck の指摘も出る（中に入っていることの確認） |
| 3 | 作業用フォルダに `FROM python:latest` の Dockerfile を置き、hadolint を実行 | 異常 | DL3007 で失敗する |
| 4 | このリポジトリの `Dockerfile`・`Dockerfile.dev` に、CI と同じ引数で hadolint を実行（直す前） | 異常 | 4 件で失敗する（**Red**。上の表と同じ指摘） |
| 5 | DL3066 を `USER 10001` に直し、DL3008 に 1 件ずつ除外のコメントを書いて再実行 | 正常 | 通る（**Green**） |
| 6 | 5 の除外のコメントが 1 件ずつしか効かないこと：作業用フォルダで、除外のコメントの後に 2 つ目の `apt-get install` を足して実行 | 境界 | 2 つ目は DL3008 で失敗する（まとめて外していないこと） |
| 7 | このリポジトリの `.github/workflows/` に actionlint と zizmor を実行 | 正常 | 通る（**Red にならない**：いまの時点で指摘がない。表のとおり） |
| 8 | CI の手順をそのまま取り出し、Actions と同じ `bash -e` で実行。1〜3 の悪いファイルでも実行 | 異常・正常 | このリポジトリでは 0、悪いファイルでは 0 以外（終了コードが手順の失敗につながること。zizmor の 11〜14 も失敗になること） |
| 9 | `docker build` した API のイメージを起動し、`id -u` が 10001。`Dockerfile.dev` のイメージで pytest・nbmake | 正常 | 動くユーザーが変わらない。既存のテストが通る（**Red にならない、いまの動作を守る確認**） |
| 10 | 既存の確認（ruff・ruff format・mypy） | 正常 | 通る（コードは変えないので **Red にならない**） |
| 11 | この PR で `ci.yml` が動く | 正常 | 3 つの手順が成功する（人間が Actions の画面で確認） |

## 追加する依存パッケージ

Python の依存はなし。CI で使うものを 3 つ足す（承認が要る。質問 5）：

| もの | 理由 | 代替案 |
|---|---|---|
| **（おすすめ）`ghcr.io/zizmorcore/zizmor:v<版>@sha256:<digest>`** を `docker run` | spec の検査そのもの。トークンを渡さずに offline で動く。手元と CI で同じイメージ | zizmor-action（今回のページに記述がなく、確かめていない）、`uvx zizmor`（PyPI の wheel は「best-effort」と書かれている） |
| **（おすすめ）`rhysd/actionlint:<版>@sha256:<digest>`** を `docker run` | shellcheck が中に入っている（runner の shellcheck の版に左右されない） | 公式の download script（`curl` でスクリプトを取ってきて実行する。固定しにくい） |
| **（おすすめ）`hadolint/hadolint:v<版>@sha256:<digest>`** を `docker run` | README の公式の実行例が Docker | hadolint-action（今回は確かめていない） |

- 版と digest は、実装時に各リポジトリの Releases とレジストリで確かめる（上の `:latest` の digest は参考）。
- イメージの取得先：`ghcr.io`（zizmor）、Docker Hub（actionlint・hadolint）。hadolint は `ghcr.io/hadolint/hadolint` もあるので、そちらを使えば取得先が 1 つ減る（実装時に同じ版があるかを確かめる）。

## セキュリティ上の注意

- 入力検証：アプリの入力は変えない。
- シークレット：3 つの検査にトークンを渡さない（zizmor は offline。`GITHUB_TOKEN` を環境変数で渡さない）。リポジトリは読み取り専用で載せる。
- 外部通信（ホスト・タイムアウト）：イメージの取得（`ghcr.io`・Docker Hub）だけ。検査そのものは `--network none` で動かす（手元で動くことは確かめた）。ジョブの `timeout-minutes: 15` はそのまま。
- 権限：`permissions: contents: read` のまま変えない。
- 除外を増やしすぎない：1 命令ずつ、理由をコメントに書く。`global ignore`・`.hadolint.yaml`・`--failure-threshold` の引き上げは使わない。

## リスク・未決事項

1. **DL3008 を除外すると、OS のパッケージの版は固定されない**。`apt-get update` のたびに、そのときの最新（セキュリティの修正を含む）が入る。固定すると、Debian が古い版を消したときにビルドが壊れ、Dependabot も上げられない。中身の脆弱性は #21 の Trivy で見る（質問 1）。
2. **ツールの版を上げると、新しいルールで急に CI が落ちる**ことがある。digest で固定しているので勝手には変わらない。上げるときは手で、その PR で指摘を直す。
3. **zizmor の offline では、Action の既知の脆弱性・偽のコミット（impostor commit）の監査が動かない**。Action は SHA で固定し、Dependabot が更新している。online にするかは質問 4。
4. **`USER 10001`** にしても、名前の `appuser` は `/etc/passwd` に残る。`docker run --user` などで名前を使っている所はない（`grep` で確かめた。`Dockerfile.dev` の `chown -R appuser` だけで、これは root で動く命令）。
5. CI の結果（テスト 11）は AI から見えない。PR の Actions の画面で人間が確かめる。

## ブロッカー（人間の対応が必要なこと）

- なし（Docker Desktop は動いていることを確かめた。必要な外部 API の項目もない）。

## 質問

未回答：なし

回答済み（2026-10-16、人間の回答「おすすめで進めてください」）：

- 質問 1：A。DL3008 は 1 か所ずつ理由のコメントを書いて除外する。
- 質問 2：zizmor の persona は既定の `regular`。
- 質問 3：A。zizmor の対象は `.github/workflows/` だけ。`dependabot.yml` の cooldown は別の Issue の候補。
- 質問 4：zizmor は offline（トークンを渡さない、`--network none`）。
- 質問 5：3 つのツールの公式の Docker イメージを、版のタグ + digest で固定して導入する。
- 質問 6：ブランチは `feature/issues_39`。

以下は、レビューのときに示した質問の原文。

1. **DL3008（`apt-get install` の版の固定）をどうするか**（2 か所）
   - **A（おすすめ）：1 か所ずつ `# hadolint ignore=DL3008 # 理由` で除外する**。理由：Debian は古い版を消すので、固定するとそのうちビルドが壊れる。セキュリティの修正を受け取るため最新を入れる。中身は #21 の Trivy で見る。
   - B：`libgomp1=<版>` で固定する（リスク 1 のとおり、壊れたら手で直す）。
2. **zizmor の persona**：**おすすめは既定の `regular`**（いまの指摘 0 件）。`pedantic` 以上にすると、ジョブの `name:` や権限の説明のコメントを足す変更が入る（上の表の 3 件。spec の受け入れ条件の外）。
3. **`dependabot.yml` を zizmor の対象に入れるか**：spec は `.github/workflows/`。入れると `dependabot-cooldown`（medium）が 3 件出て、Dependabot に「新しい版が出てから N 日待つ」設定を足すことになる（更新の動き方が変わる）。
   - **A（おすすめ）：#20 では spec どおり `.github/workflows/` だけ**。cooldown は、サプライチェーンの攻撃（出たばかりの悪い版）を避ける意味があるので、別の Issue の候補にする。
   - B：#20 に入れる（spec の #20 の受け入れ条件を書き直す）。
4. **zizmor を online で動かすか**：**おすすめは offline**（トークンを渡さない、`--network none` で動く、gitleaks と同じ形）。online にすると `api.github.com` と通信し、`GITHUB_TOKEN`（`contents: read`）をコンテナに渡すことになる。
5. **3 つのツールの導入（上の「追加する依存パッケージ」の表）を承認するか**。どれも公式の Docker イメージを版のタグ + digest で固定して `docker run`。
6. **ブランチ名**：`feature/issues_39`（Issue 番号）でよいか。

## 実装時の変更

- **版と digest**（2026-10-16。版は GitHub の Releases の API、digest は `docker buildx imagetools inspect` でレジストリから取得。どれも複数の CPU 向けのまとめ（image index））：
  - actionlint `1.7.12`（2026-03-30 公開）：`sha256:b1934ee5f1c509618f2508e6eb47ee0d3520686341fec936f3b79331f9315667`（`:latest` と同じ）。
  - hadolint `v2.15.1`（2026-07-31 公開）：`sha256:32dac94127fd60b7b7e3fbfc65e1383b9b5e25c9bfd7b8536de7a539fe68a12d`。`hadolint/hadolint` と `ghcr.io/hadolint/hadolint` で同じ digest だったので、**ghcr.io の方を使う**（取得先が ghcr.io と Docker Hub の 2 つになる）。
  - **zizmor は最新の `1.31.1` ではなく `1.30.1`（2026-09-09 公開）**：`sha256:a2eb396d886c053073405c7a980f2139ba2248ec172243cfa3841e57196e8101`。1.31.1 は前日（2026-10-15）に出たばかりで（同じ日に 1.31.0 も出ている）、出たばかりの版を避けるため（人間の回答「おすすめで」、2026-10-16）。ghcr.io のタグには `v` が付かない（`1.30.1`。`v1.31.1` は not found）。
- **actionlint は git のリポジトリの中でないとワークフローを見つけない**（`no project was found in any parent directories`、終了コード 3）。テスト 2 の見本は `git init` してから実行した。CI の作業フォルダは git のリポジトリなので、そのまま動く。見つからないときも 0 以外なので、見ないまま通ることはない。
- **除外の書き方**：理由は `# hadolint ignore=DL3008` の上の行のコメントに書き、`ignore` の行は `RUN` の直前に置いた。間に行を 1 つ挟むと除外が効かず DL3008 が出る（わざと壊して確かめた）。
- **テストの結果**：
  - Red（テスト 1〜4）：zizmor 14（1.31.1・1.30.1 とも）、actionlint 1（綴りの誤りと shellcheck の SC2086）、hadolint 1（DL3007）、このリポジトリの hadolint 4 件で 1。
  - Green（テスト 5〜8）：`ci.yml` の 3 つの手順の `run:` をそのまま取り出して `bash -e` で実行。このリポジトリでは 3 つとも 0（新しい `ci.yml` 自身も actionlint・zizmor を通る）、悪い見本では actionlint 1・zizmor 14・hadolint 1。除外のコメントの次の 2 つ目の `apt-get install` は DL3008 で失敗（テスト 6）。
  - テスト 9：API のイメージ・`Dockerfile.dev` のイメージとも `uid=10001(appuser) gid=999(appuser)`（`USER appuser` のときと同じ）。API のイメージで `scripts/smoke_test.py` が通る（`--network none`）。`Dockerfile.dev` の中で pytest 1796 件通過・カバレッジ 99.59%、nbmake 8 件通過。
  - テスト 10：ruff・ruff format・mypy（52 ファイル）が通る。
- **わざと壊して見つけたこと**（作業用フォルダのコピーで 1 か所ずつ）：`USER appuser` に戻す → DL3066 で 1。除外のコメントを消す → DL3008 で 1。除外と `RUN` の間に行を挟む → DL3008 で 1。`Dockerfile.dev` がない → 1。zizmor の対象のパスの誤り → 1。対象のフォルダにワークフローがない → 3。どれも失敗になり、見ないまま通るものはなかった。
