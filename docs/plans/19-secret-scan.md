# 計画：#19 シークレットのコミット防止（Issue #36）

状態：承認済み（2026-10-16、人間の回答「おすすめで進めてください」）

## 目的と受け入れ条件

spec.md「14. 機能一覧」より：

> | 19 | シークレットのコミット防止 | GitHub の secret scanning と Push protection が有効なことを、人間が設定画面で確かめて記録する。CI で gitleaks がリポジトリの全履歴を検査し、見つかったら失敗する。検出されることの確かめ方は計画で決める（本物のシークレットは使わない） | 未着手 |

spec.md「11. セキュリティ要件」より：

> - シークレット混入対策：GitHub の secret scanning を有効化（実際に有効かどうかは #19 で確認する）。
> - ツール・Action を足すときは、計画に理由を書いて承認を得る。Action はほかと同じくコミットの SHA で固定する。
> - ツールの設定・引数・出力の形式は推測で書かない。公式ドキュメントで確かめ、確かめたことを計画に書く。
> - 検査で見つかった既存の指摘は、直すか、理由をコメントに書いて 1 件ずつ除外する。
> - 検査の結果に、シークレットを出さない。

たとえ：工場の出荷口に立つ「鍵の持ち出し検査係」。

| 係 | どこに立つか | 何をするか |
|---|---|---|
| Push protection（GitHub） | 倉庫（GitHub）の入口 | 鍵らしいものが入った箱（push）を、入口で止める |
| gitleaks（CI） | 倉庫の中を見回る | 倉庫にある箱をすべて（全履歴）開けて、鍵が紛れていないかを見る |

## 調べたこと（2026-10-16。どれも WebFetch の要約で読んだ。原文は読んでいない）

**GitHub の secret scanning**（公式ドキュメント「About secret scanning」）：

- public のリポジトリは無料で自動に動く。
- **個人のアカウントの private のリポジトリでは使えない**（使えるのは GitHub Enterprise Cloud の Enterprise Managed Users か、GitHub Enterprise Server で Secret Protection を有効にした場合だけ）。
- #18 の時点で、リポジトリは private（#14 の計画）。**このままでは受け入れ条件の「secret scanning が有効」を満たせない**（ブロッカー 1）。

**Push protection for users**（公式ドキュメント「Push protection for users」）：

- 設定の場所：右上のプロフィールの画像 → Settings → サイドバーの「Code security」→「User」の見出しの「Push protection for yourself」。
- 既定で有効か、private のリポジトリへの push にも効くかは、**このページには書かれていなかった**。推測では書かない（ブロッカー 1、質問 1）。

**gitleaks**（README、`github.com/gitleaks/gitleaks`）：

- 検査のしかた：`gitleaks git`（ローカルの git リポジトリ。`git log -p` の結果を見る。`--log-opts` で `git log` の引数を変えられる）・`gitleaks dir`・`gitleaks stdin`。
- 引数：`--redact`（ログと標準出力でシークレットを伏せる）、`--exit-code`（見つかったときの終了コード。既定 1）、`--no-banner`、`--config`/`-c`、`--baseline-path`/`-b`、`--report-format`（json・csv・junit・sarif・template）。
- 終了コード：0 は見つからない、1 は見つかった（またはエラー）、126 は知らない引数。
- 除外：リポジトリの直下の `.gitleaksignore` に指摘の fingerprint（`commit:file:rule-id:line`）を書く（README では「experimental」）。または、その行に `gitleaks:allow` のコメントを書く。
- 公式の Docker イメージ：`zricethezav/gitleaks`（Docker Hub）・`ghcr.io/gitleaks/gitleaks`。README に最新の版は書かれていない（pre-commit の例が `v8.24.2`）。
- README に「Gitleaks is feature complete」（新しい機能はもう足さない。作者は Betterleaks に移る）と書かれている（リスク 2）。

**gitleaks-action**（README、`github.com/gitleaks/gitleaks-action`）：

- 個人のアカウントのリポジトリでは license key は要らない（organization では無料の key が要る）。
- `GITHUB_TOKEN` を使い、PR にコメントを書く。例では `actions/checkout` に `fetch-depth: 0`。
- PR のときに全履歴を見るのか、PR のコミットだけを見るのかは **README に書かれていない**。

## 今回やらないこと

- #20 以降の検査（zizmor・Trivy など）
- pre-commit のフック（手元でコミットの前に止める仕組み）。手元の環境に依存し、spec にない
- `cd.yml` に gitleaks を足すこと（spec は `ci.yml`）
- gitleaks の独自のルール（`.gitleaks.toml`）を作ること。既定のルールで始める
- リポジトリを public にすること（質問 1 の B を選んだ場合は、別の Issue で公開の見直しをしてから）

## 変更・追加するファイル

| ファイル | 内容 |
|---|---|
| `.github/workflows/ci.yml` | `actions/checkout` に `fetch-depth: 0` を足す。最初の手順として gitleaks の手順を足す（質問 2 の方法で。`--redact` を付ける） |
| `.gitleaksignore` | 既存の履歴に指摘があり、本物でないものだけ（1 件ずつ。理由はコメントに書く）。指摘がなければ作らない |
| `docs/security-settings.md`（新規） | 人間が設定画面で確かめた結果（日付・画面の名前・状態）。質問 3 |
| `docs/spec.md` | #19 の状態。「11. セキュリティ要件」の secret scanning の行と、「13. CI/CD」の `ci.yml` の内容に gitleaks を足す。質問 1 の答えで受け入れ条件の文言が変わる場合はその文言 |

- 全履歴を見るため、`ci.yml` の checkout を `fetch-depth: 0` にする（既定の 1 では最新のコミットしかない）。ほかの手順にも効くが、履歴が 82 コミットと小さいので時間はほとんど変わらない見込み。
- gitleaks の手順は ruff より前（いちばん最初）に置く。速く終わり、シークレットが入っていたら、ほかの手順のログを出す前に止まる。

## テスト一覧（先に書く順）

gitleaks は pytest のユニットテストの対象にならない。gitleaks を実行して確かめる。

| # | 確認 | 種類（正常/異常/境界） | 確かめること |
|---|---|---|---|
| 1 | 作業用フォルダ（scratchpad）に使い捨ての git リポジトリを作り、**偽のシークレット**をコミットして、CI と同じイメージ・同じ引数で `gitleaks git` を実行 | 異常 | 終了コード 1 で失敗する（**Red**：検査係が本当に見ていること） |
| 2 | 1 の出力に、偽のシークレットの値が出ていないこと | 異常 | `--redact` が効いている（spec「検査の結果に、シークレットを出さない」） |
| 3 | 1 のリポジトリで、偽のシークレットを**消すコミット**を足して再実行 | 境界 | それでも失敗する（全履歴を見ていること。いまのファイルだけでなく過去のコミットも見る） |
| 4 | 1 のリポジトリで、`.gitleaksignore` にその 1 件の fingerprint を書いて再実行 | 正常 | 通る（除外が 1 件ずつ効くこと）。既存の指摘を除外する場合だけ行う |
| 5 | このリポジトリの全履歴に、CI と同じ引数で `gitleaks git` を実行 | 正常 | 通る。指摘があれば、1 件ずつ中身を人間と確かめて、本物なら作業を止める（下の「リスク」1）。本物でなければ `.gitleaksignore` に理由つきで書く（**Red にならないことがある**：いまの履歴に指摘がなければ、最初から通る） |
| 6 | この PR で `ci.yml` が動く | 正常 | gitleaks の手順が成功し、ログに全履歴のコミット数（82 前後）が出る（人間が Actions の画面で確認） |
| 7 | 既存の確認（ruff・mypy・Docker の中で pytest・nbmake） | 正常 | すべて通る（`ci.yml` 以外のコードは変えないので、**Red にならない、いまの動作を守る確認**） |
| 8 | 人間が GitHub の設定画面で、secret scanning と Push protection の状態を見る | 正常 | 結果を `docs/security-settings.md` に記録する（質問 1・3） |

偽のシークレット（テスト 1）：

- gitleaks の既定のルールに当たる形の文字列を、その場で乱数から作る（どのルールに当てるかは、実装時に gitleaks の既定の設定ファイルを読んで決める。推測で書かない）。
- 作業用フォルダの中だけで使い、このリポジトリにはコミットしない。実行のあとで作業用フォルダを消す必要はない（セッションごとのフォルダ）。
- このリポジトリの PR に偽のシークレットを入れて CI を落とす確かめ方は採らない（質問 4）。

## 追加する依存パッケージ

Python の依存はなし。CI で使うものを 1 つ足す（質問 2）：

| もの | 理由 | 代替案 |
|---|---|---|
| **（おすすめ）gitleaks の公式の Docker イメージ `ghcr.io/gitleaks/gitleaks:v<版>@sha256:<digest>`** を `docker run` で実行 | トークンが要らない（`contents: read` のまま）。PR にコメントを書かない（コメントにシークレットが出る心配がない）。引数を自分で決められるので、全履歴を見ることが確かめられる。手元と CI で同じイメージを使える | gitleaks-action（下） |
| gitleaks-action（SHA で固定） | Dependabot が更新できる | `GITHUB_TOKEN` と PR へのコメントの権限が要る。PR のときに全履歴を見るかが README に書かれていない |

- 版と digest は、実装時に GitHub の Releases と ghcr.io で確かめる。
- Docker のイメージを `ci.yml` の中で `docker run` するので、**Dependabot は更新しない**（いまの uv の版の行と同じ。コメントにそう書く）。

## セキュリティ上の注意

- 入力検証：アプリの入力は変えない。
- シークレット：`--redact` で出力から伏せる。テストの偽のシークレットは作業用フォルダだけで使い、コミットしない。本物のシークレットは使わない。
- 外部通信（ホスト・タイムアウト）：CI で `ghcr.io` からイメージを取得する。gitleaks 自体は外部と通信しない（README に通信の記述はない。実装時に `--network none` で実行して確かめる）。ジョブの `timeout-minutes: 15` はそのまま。
- 権限：`permissions: contents: read` のまま変えない。
- `.gitleaksignore` を増やしすぎない：1 件ずつ、理由をコメントに書く。ルールやファイルごとには外さない。

## リスク・未決事項

1. **いまの履歴に本物のシークレットが見つかった場合**：その時点で作業を止めて人間に知らせる。値は表示しない（`--redact`）。鍵の無効化（取り消し）は人間が行う。履歴の書き換えはしない（CLAUDE.md）。
2. **gitleaks は新しい機能を足さない**（README）。ルールの更新が止まると、新しい形の鍵を見落とすことがある。#19 では gitleaks を使い、Betterleaks などへの乗り換えは、必要になったら別の Issue にする。
3. **`tests/app/test_config.py` の `DUMMY_PASSWORD`** などのダミーの値が、既定のルールに当たるかもしれない。当たったら、テスト 5 の手順で 1 件ずつ除外する。
4. **`.gitleaksignore` は「experimental」**（README）。版を上げたときに形式が変わったら、その PR で直す。
5. **手元で Docker が動いていない**（2026-10-16 の計画の時点で、Docker Desktop のエンジンに接続できなかった）。そのため、いまの履歴を計画の前に検査していない。実装の最初に Docker Desktop を起動してもらう必要がある。

## ブロッカー（人間の対応が必要なこと）

1. **GitHub の secret scanning は、個人の private のリポジトリでは使えない**（上の「調べたこと」）。Push protection for users が private のリポジトリに効くかは、公式ドキュメントで確かめられなかった。どうするかは質問 1。
   - リポジトリがいま private かどうかは、`gh` がないので AI からは確かめられない。設定画面で確かめてください。
2. **設定画面の確認**（受け入れ条件）は人間しかできない：
   - リポジトリの Settings → 「Advanced Security」（または「Code security」）の secret scanning・Push protection の欄
   - プロフィールの Settings → Code security → 「Push protection for yourself」
3. 実装の前に、手元の Docker Desktop を起動してください（リスク 5）。
4. CI の結果（テスト 6）は AI から見えない。PR の Actions の画面で人間が確かめる。

## 質問

未回答：なし

回答済み（2026-10-16、人間の回答「おすすめで進めてください」）：

- 質問 1：A。リポジトリの secret scanning は「公開するときに有効にする」として #19 から外す。#19 では設定画面の「いまの状態」と「Push protection for yourself」の状態を記録し、spec の #19 の受け入れ条件と「11. セキュリティ要件」の行を書き直す。
- 質問 2：公式の Docker イメージを digest で固定して `docker run`。
- 質問 3：新しいファイル `docs/security-settings.md` に記録する。
- 質問 4：作業用フォルダの使い捨てのリポジトリで、CI と同じイメージ・引数を使って確かめる（テスト 1〜3）。
- 質問 5：ブランチは `feature/issues_36`。

以下は、レビューのときに示した質問の原文。

1. **secret scanning が private では使えない件をどうするか**
   - **A（おすすめ）：#18 の CodeQL と同じく、リポジトリの secret scanning は「公開するときに有効にする」として #19 から外す**。#19 では、人間が設定画面で見た「いまの状態」（使えない・無効など）と、「Push protection for yourself」の状態をそのまま記録する。spec の #19 の受け入れ条件と「11. セキュリティ要件」の行をそのように書き直す。private のあいだは gitleaks が守る。
   - B：いまリポジトリを public にする（公開の見直しが先に要るので、別の Issue）。
   - C：有料のプランを使う。
2. **CI での gitleaks の動かし方**：**おすすめは公式の Docker イメージを digest で固定して `docker run`**（上の「追加する依存パッケージ」の表）。代案は gitleaks-action を SHA で固定。
3. **設定画面の確認の記録先**：**おすすめは新しいファイル `docs/security-settings.md`**（#20〜#24 の設定の確認も同じ所に足せる）。代案：`docs/dev-log.md` の #19 の記録に書く。
4. **検出されることの確かめ方**：**おすすめは、作業用フォルダの使い捨てのリポジトリで、CI と同じイメージ・引数を使う（テスト 1〜3）**。CI そのものが落ちることは確かめない。
   - 代案：使い捨ての別ブランチに偽のシークレットを入れて PR を出し、CI が落ちることを見てから、人間が PR を閉じてブランチを消す。全履歴を検査するので、そのコミットが main に入ると以後ずっと落ちる。誤ってマージしないよう注意が要る。
5. **ブランチ名**：手元に `feature/issues_19`（以前の Issue #19、ベースライン）がすでにある。今回は Issue 番号の `feature/issues_36` にする（CLAUDE.md の決まりどおり）。これでよいか。

## 実装時の変更

- **gitleaks の版と digest**（2026-10-16）：`v8.30.1`（2026-03-21 公開。GitHub の Releases の API で確かめた）。digest は `sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f`（ghcr.io のレジストリの API から直接取得。複数の CPU 向けのまとめ（image index））。
- **偽のシークレットのルール**：gitleaks の v8.30.1 の既定の設定ファイル（`config/gitleaks.toml`。原文を取得して読んだ）の `github-pat`（`ghp_[0-9a-zA-Z]{36}`、エントロピー 3 以上）。`ghp_` と乱数 36 文字で作り、作業用フォルダの中だけで使った。
- **イメージの中の git**：イメージは root で動き、`safe.directory=*` が設定済み（`docker image inspect` と、イメージの中で `git config --global --list` を実行して確かめた）。所有者の違いで git が止まることはない。
- **テスト 5・6 の「コミット数」**：計画では「82 前後」と書いたが、gitleaks の「commits scanned」は、マージのコミットと、行を消すだけのコミットを数えない。このリポジトリでは 82 コミットのうち `64 commits scanned`（マージでないコミットが 64）。テスト 6 は「64 前後と、この PR のコミット」で確かめる。
- **わざと壊して見つけたこと**（実装手順 7）：
  - `--redact` を外す → 偽の値がログに 2 行出た（テスト 2 で検出）。
  - **浅い履歴（`fetch-depth: 0` を消したのと同じ）→ `1 commits scanned` で終了コード 0**。過去のコミットを見ずに通る。
  - **git のリポジトリでない（中の git が失敗）→ ERR の行が出るのに終了コード 0**。README の「1 - leaks or error encountered」と違う。
  - 人間の回答（2026-10-16「おすすめで進めてください」）で、同じ手順に見張りを 2 つ足した：
    1. gitleaks の前に `git rev-parse --is-shallow-repository` が `false` でなければ失敗にする。
    2. gitleaks の出力を `tee` で `${RUNNER_TEMP}/gitleaks.log` に残し、「時刻 ERR」で始まる行があれば失敗にする。`set -o pipefail` で、`tee` を挟んでも gitleaks の終了コードを失わない。
  - 最初は `grep -qw "ERR"` にしたが、ログに色の制御文字（`ESC[31mERR`）が付き、`ERR` の前の `m` のために単語として一致せず、見張りが効かなかった（見張りだけを残した版で終了コード 0）。制御文字を `sed` で消してから `^[^ ]+ ERR ` を探す形に直した。
  - 見張りを 1 つずつ外した版でも確かめた：浅い履歴の見張りを外すと浅い履歴で 0、ERR の見張りだけにすると git でないフォルダで 1（見張りが効く）、両方外すと 0。
- **最終の結果**（`ci.yml` の手順をそのまま取り出し、Actions と同じ `bash -e` で実行）：このリポジトリ 0（`no leaks found`）、偽のシークレット 1、浅い履歴 1、git でないフォルダ 1。どれもログに偽の値は出ていない。
- **既存の指摘はなかった**ので、`.gitleaksignore` は作っていない。テスト 4（除外が 1 件ずつ効くこと）は使い捨てのリポジトリで確かめた。
- **テスト 7**：ruff・ruff format・mypy（52 ファイル）が通る。Docker（`Dockerfile.dev`）の中で pytest 1796 件通過・カバレッジ 99.59%、nbmake 8 件通過。
- **リポジトリを public にした**（2026-10-16、人間が実施。実装の途中で知らされた）。質問 1 の A（「private では使えないので、公開するときに有効にする」）は前提がなくなった。public では secret scanning を無料で使えるので、人間がリポジトリの「Secret Protection」と「Push protection」を有効にした。spec の #19 の受け入れ条件は書き直さず、もとのまま満たす。
- **設定画面の記録**：人間のスクリーンショット 3 枚（リポジトリの Code security の画面 2 枚、プロフィールの Code security の画面 1 枚）をもとに `docs/security-settings.md` に書いた。3 つとも有効（ボタンが「Disable」）。調べたことで「書かれていなかった」とした「Push protection for yourself が private に効くか」は、画面の説明文に「across all public repositories on GitHub」とあった。
