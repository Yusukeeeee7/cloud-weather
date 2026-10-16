# 計画：#21 イメージの検査（Issue #41）

状態：承認済み（2026-10-16、人間の回答「おすすめで進めてください」）

## 目的と受け入れ条件

spec.md「14. 機能一覧」より：

> | 21 | イメージの検査 | `Dockerfile` のベースイメージと uv のイメージを digest で固定し、Dependabot が更新できる形にする。CI（PR）と CD（スモークテストの後、push の前）で Trivy がイメージを検査し、修正版のある HIGH・CRITICAL の脆弱性があれば失敗する（CD では push しない） | 未着手 |

spec.md「11. セキュリティ要件」の共通の決まりより：

> - ツール・Action を足すときは、計画に理由を書いて承認を得る。Action はほかと同じくコミットの SHA で固定する。
> - ツールの設定・引数・出力の形式は推測で書かない。公式ドキュメントで確かめ、確かめたことを計画に書く。
> - 検査で見つかった既存の指摘は、直すか、理由をコメントに書いて 1 件ずつ除外する。ルールや検査をまとめて外して通さない。
> - 検査が外部と通信するもの（脆弱性のデータベースの取得など）は、通信先を計画に書く。アプリのコンテナは、これまでどおり外部と通信させない。

たとえ：工場の「出荷前の部品の検品係」。#20 は手順書を見たが、#21 は**できあがった箱（イメージ）を開けて、中の部品（OS のパッケージ・Python のライブラリ）を、リコールの一覧（脆弱性のデータベース）と照らし合わせる**。

| 決まり | たとえ | この機能でやること |
|---|---|---|
| digest で固定 | 部品の仕入れ先を「型番」でなく「ロット番号」で指定する | `python:3.14-slim` と uv のイメージに `@sha256:...` を付ける |
| Dependabot が更新できる形 | ロット番号を書き換える係が読める書式にする | uv のイメージを `FROM` の行に移す（下の「調べたこと」の 3） |
| 修正版のある HIGH・CRITICAL で失敗 | リコールのうち「交換部品がもう出ている重いもの」だけで出荷を止める | Trivy を `--severity HIGH,CRITICAL --ignore-unfixed --exit-code 1` で実行 |

## 調べたこと（2026-10-16）

**1. Trivy の公式ドキュメント**（`trivy.dev` の Installation・Container Image・Filtering・CLI リファレンス。どれも WebFetch の要約で読んだ。原文は読んでいない）：

- 公式のイメージ：`docker.io/aquasec/trivy`、`ghcr.io/aquasecurity/trivy`、`public.ecr.aws/aquasecurity/trivy`。
- ローカルのイメージの検査：既定では Docker Engine（ソケット）→ containerd → Podman → レジストリの順に探す。**`docker save` で tar にして `trivy image --input <tar>` でも検査できる**（公式の例：`docker save ruby:3.1-alpine3.15 -o ruby-3.1.tar` → `trivy image --input ruby-3.1.tar`）。
- 公式の `docker run` の例は Docker のソケット（`/var/run/docker.sock`）を載せている。**ソケットを渡すとコンテナがホストの Docker を自由に操作できる**ので、この計画では使わない（tar を読み取り専用で渡す）。
- `--severity`：表示する重さ。既定は `UNKNOWN,LOW,MEDIUM,HIGH,CRITICAL`。
- `--ignore-unfixed`：修正版のあるもの（status が `fixed`）だけ出す（`--ignore-status affected,will_not_fix,fix_deferred,end_of_life` の短縮）。
- `--exit-code`：指摘があったときの終了コード（既定の値はページに書かれていない。下の実験で、付けないと指摘があっても 0 のはず → 必ず `--exit-code 1` を付ける）。
- `.trivyignore`：1 行に 1 つの ID、`#` でコメント、`exp:YYYY-MM-DD` で期限。`--ignorefile` の既定は作業フォルダの `.trivyignore`。
- 脆弱性のデータベースの取得先（`--db-repository` の既定）：`mirror.gcr.io/aquasec/trivy-db:2` → `ghcr.io/aquasecurity/trivy-db:2`。Java のデータベースも同様（このイメージに Java はないので取得されない想定。実装時に確かめる）。

**2. 手元の Trivy で確かめた引数**（`ghcr.io/aquasecurity/trivy:0.75.0` の `--help`）：

- `--download-db-only`（データベースの取得だけ）、`--skip-db-update`（取得しない）、`--offline-scan`（依存を調べるための API を呼ばない）、`--skip-version-check`（新しい版のお知らせを取りに行かない）、`--disable-telemetry`（Aqua への匿名の利用データを送らない）、`--scanners`（既定は `vuln,secret`）、`--cache-dir`（既定 `/root/.cache/trivy`）、`-q`（ログを抑える）。

**3. Dependabot（docker）の仕組み**（`dependabot-core` のソース `docker/lib/dependabot/docker/file_parser.rb`・`file_fetcher.rb` を WebFetch の要約で読んだ。公式ドキュメントの Docker の節には、対応する命令の説明がなかった）：

- **読むのは `FROM` の行だけ**。`COPY --from=<イメージ>` は読まない。→ いまの `COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /bin/` は **Dependabot に更新されない**。
- `FROM` の行の書式：`FROM [--platform=..] [レジストリ/]イメージ[:タグ][@sha256:<64桁>] [AS 名前]`。タグと digest を両方書ける。
- 対象のファイル名：名前に `dockerfile` か `containerfile` を含むもの（大文字小文字を区別しない）→ `Dockerfile.dev` も対象。
- 外部の解説（Chainguard）によると、digest がすでに付いていれば更新するが、付いていない行に digest を足すことはしない。

**4. Trivy のサプライチェーン攻撃（2026 年 3 月、CVE-2026-33634）**（Aqua の blog と各社の解説を検索の要約で読んだ）：

- 3 月 19 日に `aquasecurity/trivy-action`（77 個中 76 個のタグ）と `setup-trivy`（全タグ）が悪いコミットに付け替えられ、悪い Trivy v0.69.4 が公開された。3 月 22 日には Docker Hub に悪い v0.69.5・v0.69.6 のイメージ。
- → **trivy-action は使わない**。イメージを**版と digest で固定**して `docker run` する（#19・#20 と同じ形）。取得先は ghcr.io（悪いイメージが出たのは Docker Hub と報じられている。ほかの検査のイメージとも取得先がそろう）。

**5. 手元で実行して確かめたこと**（Docker Desktop 29.6.2。リポジトリのファイルは変えていない）：

| 確かめたこと | 結果 |
|---|---|
| 版の候補 | 最新は v0.76.0（2026-10-14 公開、2 日前）。出たばかりを避けて **v0.75.0（2026-10-01）** にする（#20 の zizmor と同じ考え） |
| `ghcr.io/aquasecurity/trivy:0.75.0` と `aquasec/trivy:0.75.0` の digest | どちらも `sha256:af6acf9a6b85dfe389a1941505c0ce9efef52a4719635e1a962f022a3d855daa` |
| `python:3.14-slim` の digest | `sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170`（実装時に取り直す） |
| `ghcr.io/astral-sh/uv:0.13.0` の digest | `sha256:cdc6093146eb3ff6a40107b38f008b789e050e77ad87865e381d9917da55a168`（同上） |
| いまの API のイメージを `--severity HIGH,CRITICAL --ignore-unfixed --exit-code 1` で検査 | **4 件で失敗（終了コード 1）**。OS（Debian 13.7）は 0 件 |
| 4 件の中身 | `msgpack` 1.1.2（GHSA-6v7p-g79w-8964、修正 1.2.1）、`setuptools` 70.3.0（CVE-2025-47273、修正 78.1.1）、`urllib3` 2.7.0（CVE-2026-97687・CVE-2026-97689、修正 2.8.0） |
| 4 件の出どころ | **ベースイメージの pip（26.2.1）が中に抱えている部品**（`pip/_vendor/vendor.txt` に同じ版がある）。`python:3.14-slim` だけを検査しても同じ 4 件。アプリの `.venv` は 0 件（`uv.lock` の msgpack は 1.2.3） |
| `--ignore-unfixed` を外すと | ベースイメージだけで 48 件（修正版のないもの。受け入れ条件の対象外） |
| 最後の段で `/usr/local/bin/python -m pip uninstall -y pip` を足したイメージを検査 | **0 件（終了コード 0）**。`python -c "import app.main"` は動く。`/usr/local/bin` に pip が残らない |
| データベースを取得した後、`--network none --skip-db-update --offline-scan` で検査 | 動く（上と同じ結果） |

- pip の消し方の注意：最後の段は `PATH` の先頭が `/app/.venv/bin` なので、`python -m pip` は仮想環境の python（pip なし）になり失敗した。システムの `/usr/local/bin/python` を明示する。

## 今回やらないこと

- SBOM・来歴（#22）、DAST（#23）
- `Dockerfile.dev` のイメージを Trivy で検査すること（手元のテスト用で配布しない。spec は API のイメージ）
- Trivy の `secret`・`misconfig` の検査（質問 3）
- 修正版のない脆弱性・MEDIUM 以下で失敗させること（spec どおり）
- Trivy のデータベースを Actions のキャッシュに置くこと（毎回取得する。速さが問題になったら別の Issue）
- Trivy のイメージの署名（cosign）の検証を CI で毎回行うこと（質問 6）
- Dependabot の `cooldown`（#20 で別の Issue の候補にしたもの）

## 変更・追加するファイル

| ファイル | 内容 |
|---|---|
| `Dockerfile` | ① `FROM python:3.14-slim@sha256:<digest>`（2 か所）。② uv を `FROM ghcr.io/astral-sh/uv:0.13.0@sha256:<digest> AS uv` の段にし、`COPY --from=uv /uv /bin/` にする（Dependabot が読める形）。③ 最後の段で、システムの pip を消す（質問 1。理由をコメントに書く） |
| `Dockerfile.dev` | ①・② と同じ形にする（質問 2。テストの環境と本番のベースをそろえ、Dependabot の 1 つの PR で一緒に上がるようにする）。pip は消さない |
| `.github/workflows/ci.yml` | `Docker build` の後に 2 つの手順：「Trivy DB」（`--download-db-only`。通信あり）、「Trivy (image)」（`docker save` → `--network none` で `--input` の tar を検査） |
| `.github/workflows/cd.yml` | `Smoke test` の後、`Log in to ghcr.io` の前に同じ 2 つの手順。失敗したら以降（push）は実行されない |
| `docs/spec.md` | #21 の状態、「13. CI/CD」の `ci.yml`・`cd.yml` の内容に Trivy を足す |

CI・CD の Trivy の手順の形（引数は上の「調べたこと」で確かめたもの。実装時に `bash -e` で手元で動かして確かめる）：

```bash
# 1) データベースの取得（mirror.gcr.io → ghcr.io。キャッシュは RUNNER_TEMP のフォルダ）
docker run --rm --volume "${RUNNER_TEMP}/trivy-cache:/root/.cache" <trivy@digest> \
  image --download-db-only --skip-version-check --disable-telemetry --no-progress
# 2) 検査（外部と通信させない。イメージは tar にして読み取り専用で渡す。Docker のソケットは渡さない）
docker save cloud-weather:ci --output "${RUNNER_TEMP}/image.tar"
docker run --rm --network none \
  --volume "${RUNNER_TEMP}/image.tar:/scan/image.tar:ro" \
  --volume "${RUNNER_TEMP}/trivy-cache:/root/.cache" <trivy@digest> \
  image --input /scan/image.tar --scanners vuln --severity HIGH,CRITICAL --ignore-unfixed \
  --exit-code 1 --skip-db-update --offline-scan --skip-version-check --disable-telemetry --no-progress
```

- イメージは `ghcr.io/aquasecurity/trivy:0.75.0@sha256:af6acf9a...`。`docker run` のイメージなので **Dependabot はこの行を更新しない**（ほかの検査と同じ。コメントに書く）。
- `.trivyignore` は作らない（いまの 4 件は「直す」で 0 件になる）。将来除外が要るときは、1 行に 1 つの ID・理由のコメント・`exp:` の期限を付ける。

## テスト一覧（先に書く順）

Trivy・Dependabot は pytest の対象にならない。ツールを実行して確かめる（#19・#20 と同じやり方）。

| # | 確認 | 種類（正常/異常/境界） | 確かめること |
|---|---|---|---|
| 1 | いまの `Dockerfile` でビルドしたイメージを、CI と同じ引数で検査（直す前） | 異常 | 4 件・終了コード 1 で失敗する（**Red**。上の表と同じ指摘。検品係が本当に見ていること） |
| 2 | `--exit-code 1` を外して 1 と同じ検査 | 異常 | 指摘があっても終了コード 0 になること（＝この引数が必須だと確かめる。結果によって書く中身が変わる確認） |
| 3 | `Dockerfile` を直し（digest・uv の段・pip を消す）、ビルドして検査 | 正常 | 0 件・終了コード 0（**Green**） |
| 4 | 3 のイメージを `--ignore-unfixed` を外して検査 | 境界 | 修正版のない HIGH・CRITICAL が残っていても、CI の引数では失敗しないこと（受け入れ条件の「修正版のある」の線引き。件数は結果を記録） |
| 5 | キャッシュが空のまま `--skip-db-update` で検査 | 異常 | **データベースがないときに 0 で通らない**こと（取得に失敗したのに検査が素通りしないか。結果によって手順を足す） |
| 6 | 3 のイメージを、CD と同じく `--network none` で起動し、`scripts/smoke_test.py` を実行。`id -u` が 10001 | 正常 | 動きが変わらない（**Red にならない、いまの動作を守る確認**） |
| 7 | `Dockerfile.dev` をビルドし直し、その中で pytest（カバレッジ）・nbmake | 正常 | 既存のテストが通る（**Red にならない**） |
| 8 | hadolint・actionlint・zizmor（#20 の CI と同じ引数）、ruff・ruff format・mypy | 正常 | 通る（新しい `FROM` の段・手順で指摘が出ないこと。出たら直す） |
| 9 | CI・CD の Trivy の手順を取り出し、Actions と同じ `bash -e` で実行。1 のイメージでも実行 | 異常・正常 | 直したイメージでは 0、直す前のイメージでは 0 以外（終了コードが手順の失敗につながること） |
| 10 | `FROM` の行が Dependabot の書式（調べたことの 3）に合うこと、タグと digest の組が正しいこと（`docker buildx imagetools inspect <タグ>` の digest と一致） | 正常 | 固定した digest が、書いたタグのものである |
| 11 | この PR で `ci.yml` が動く | 正常 | Trivy の 2 つの手順が成功する（人間が Actions の画面で確認） |
| 12 | main へのマージ後に `cd.yml` が動く | 正常 | Trivy の手順の後に push される（人間が確認。spec の状態は「実装済み（マージ後の実行で確認）」→ 確認後に「完了」） |

- Dependabot が実際に digest を上げる PR を作るかは、次の月 1 回の実行まで分からない（リスク 3）。

## 追加する依存パッケージ

Python の依存はなし。CI・CD で使うものを 1 つ足す（承認が要る。質問 4）：

| もの | 理由 | 代替案 |
|---|---|---|
| **（おすすめ）`ghcr.io/aquasecurity/trivy:0.75.0@sha256:af6acf9a...`** を `docker run` | spec の検査そのもの。版と digest で固定でき、ほかの検査と同じ形。ソケットを渡さず tar で検査できる | `aquasecurity/trivy-action`（2026 年 3 月にタグが付け替えられた。SHA で固定すれば防げるが、中で Trivy をダウンロードする所がもう 1 段増える）、Grype（spec は Trivy） |

## セキュリティ上の注意

- 入力検証：アプリの入力は変えない。
- シークレット：Trivy にトークンを渡さない（データベースは公開のレジストリから匿名で取得）。cd.yml では、`docker login` より**前**に Trivy を実行するので、ログインの情報が残った状態の Docker でも Trivy のコンテナには渡らない。
- 外部通信（ホスト・タイムアウト）：
  - イメージの取得：`ghcr.io`（trivy）、Docker Hub（python）、`ghcr.io`（uv）。
  - データベースの取得（手順 1 だけ）：`mirror.gcr.io`、取れなければ `ghcr.io`。
  - 検査（手順 2）：`--network none`。お知らせ・利用データの送信も引数で止める（`--skip-version-check`・`--disable-telemetry`）。
  - Trivy の `--timeout` は既定の 5 分。ジョブの `timeout-minutes`（CI 15・CD 20）は、実装時に PR の実行時間を見て、足りなければ質問する。
- 権限：`permissions` は変えない（ci `contents: read`、cd `contents: read`・`packages: write`）。
- Docker のソケットを検査のコンテナに渡さない。イメージの tar は `:ro`。
- 除外：`.trivyignore` は作らない。`--severity` を下げる・`--exit-code` を外すことで通さない。

## リスク・未決事項

1. **pip を消すと、動いているコンテナの中で `pip install` できなくなる**。API は pip を使わない（依存は builder の段で uv が入れる）。調べるときに困るなら、`Dockerfile.dev` のイメージを使う（質問 1）。
2. **データベースは毎日更新される**ので、コードを変えていなくても、新しい脆弱性が見つかった日から CI・CD が急に落ちる。そのときは直す（ベースイメージを上げる、依存を上げる）か、1 件ずつ期限付きで除外する。CD が落ちている間は push されない（spec どおり）。
3. **Dependabot が digest だけの更新（同じ `3.14-slim` の作り直し）の PR を作るか**は、ドキュメントに書かれておらず、外部の解説だけが根拠。次の実行（月 1 回）で確かめる。作られなければ、手で上げる手順を docs に書く（別の Issue）。
4. **Dependabot が `3.14-slim` → `3.15-slim` のような版の上げ方をする**かもしれない。そのときは PR の CI で検査されるので、そのまま採るかを人間が判断する。
5. **uv の版は 3 か所にある**（`Dockerfile`・`Dockerfile.dev`・`ci.yml` の setup-uv）。Dependabot が上げるのは Dockerfile の 2 つだけで、`ci.yml` は手で合わせる（いまのコメントのとおり）。Dependabot の PR はずれたまま通ってしまうので、ずれを CI で止める仕組みは別の Issue の候補（レビューで決定）。
6. `mirror.gcr.io`・`ghcr.io` が落ちていると、データベースが取れず失敗する（テスト 5 で、素通りしないことを確かめる）。
7. CI・CD の結果（テスト 11・12）は AI から見えない。人間が Actions の画面で確かめる。

## ブロッカー（人間の対応が必要なこと）

- なし（Docker Desktop は動いていることを確かめた。必要な外部 API の項目もない）。

## 質問

未回答：なし

回答済み（2026-10-16、人間の回答「おすすめで進めてください」）：

- 質問 1：A。API のイメージの最後の段で、システムの pip を消す（直す）。
- 質問 2：A。`Dockerfile.dev` も digest で固定し、uv を `FROM` の段にする（pip は消さない）。
- 質問 3：`--scanners vuln` だけ。
- 質問 4：`ghcr.io/aquasecurity/trivy:0.75.0` を digest で固定して導入する。データベースの取得先は `mirror.gcr.io`・`ghcr.io`。
- 質問 5：イメージは tar にして読み取り専用で渡す。Docker のソケットは渡さない。
- 質問 6：cosign の署名の確認は、実装のときに手元で 1 回だけ（公式の手順を確かめてから。cosign を手元に入れる）。
- 質問 7：ブランチは `feature/issues_41`。

以下は、レビューのときに示した質問の原文。

1. **いまの 4 件（ベースイメージの pip の中の部品）をどうするか**
   - **A（おすすめ）：API のイメージの最後の段で、システムの pip を消す（直す）**。API は pip を使わない。消したイメージで 0 件、`import app.main` が動くことを確かめた。「直す」なので除外が増えない。
   - B：`.trivyignore` に 4 件を 1 行ずつ、理由と期限（例：1 か月）を付けて除外する。ベースイメージの pip が新しくなるのを待つ。
2. **`Dockerfile.dev` も digest で固定し、uv を `FROM` の段にするか**：spec は `Dockerfile`。
   - **A（おすすめ）：する**。Dependabot は `Dockerfile.dev` も読むので、固定しないと、本番だけ上がってテストの環境が古いまま（または逆）になる。同じ PR で一緒に上がる。
   - B：しない（spec の文字どおり）。
3. **Trivy の検査の種類**：**おすすめは `--scanners vuln` だけ**（spec は脆弱性）。既定の `secret` も入れると、イメージの中のシークレットも見るが、リポジトリのシークレットは #19 の gitleaks が見ている。入れるなら、出た指摘は同じく直すか 1 件ずつ除外する。
4. **Trivy の導入（上の「追加する依存パッケージ」の表）を承認するか**。`ghcr.io/aquasecurity/trivy:0.75.0` を digest で固定して `docker run`。データベースの取得先は `mirror.gcr.io`・`ghcr.io`。
5. **検査の対象を tar にする（Docker のソケットを渡さない）**：**おすすめは tar**。ソケットの方が手順は 1 つ短いが、Trivy のコンテナがホストの Docker を操作できるようになる（3 月の攻撃のように、検査の道具が悪くなったときの被害が大きい）。
6. **Trivy のイメージの署名（cosign）を確かめるか**：**おすすめは、実装のときに手元で 1 回だけ**（公式の「Signature Verification」のページの手順を確かめてから。cosign を手元に入れる必要がある＝依存の追加）。しないなら、digest の固定だけにする。
7. **ブランチ名**：`feature/issues_41`（Issue 番号）でよいか。

## 実装時の変更

- **pip を消す命令を、`apt-get` の `RUN` につなげた**（計画では別の `RUN`）。別にすると、hadolint が DL3059（info。`RUN` が続いている）を出して失敗したため。除外せずに直した。コメントも同じ命令の上にまとめた。
- **cosign は手元に入れず、公式のイメージ `ghcr.io/sigstore/cosign/cosign:v3.1.3@sha256:9e5c2f2edc34351160407ca3416c61855bdf9403c3c5936e0f0be7fc261611b8` を 1 回だけ `docker run` した**（質問 6）。README（`github.com/sigstore/cosign`、WebFetch の要約で読んだ）に公式のイメージとして載っている。v3.1.3 は 2026-08-06 公開。
  - 手順は Trivy の「Signature Verification」のページ（WebFetch の要約で読んだ）のとおり：`cosign verify <イメージ> --certificate-identity-regexp 'https://github\.com/aquasecurity/trivy/\.github/workflows/.+' --certificate-oidc-issuer "https://token.actions.githubusercontent.com"`。
  - 結果：`ghcr.io/aquasecurity/trivy@sha256:af6acf9a...` と `aquasec/trivy@sha256:af6acf9a...` の両方で **終了コード 0、署名 2 つ**（どちらも同じ digest）。署名した側は `https://github.com/aquasecurity/trivy/.github/workflows/reusable-release.yaml@refs/tags/v0.75.0`。
  - Git Bash で実行するときは `MSYS_NO_PATHCONV=1` が要る（ないと正規表現の `\.` が `/.` に書き換えられ、照合に失敗する。1 回目はこれで失敗した）。
- 手元での確認は、`ci.yml`・`cd.yml` から「Trivy DB」「Trivy (image)」の `run:` の本文を awk で取り出し、`RUNNER_TEMP` を作業用フォルダにして `bash -e` で実行した（手元の Python に PyYAML がないため）。CI と CD の手順は、イメージの名前以外は同じ。

### テストの結果

| # | 結果 |
|---|---|
| 1 | 直す前のイメージ：`Total: 4 (HIGH: 4, CRITICAL: 0)`、終了コード 1（Red） |
| 2 | `--exit-code 1` を外すと、4 件出ても終了コード 0 |
| 3 | 直したイメージ：終了コード 0。Debian 13.7（パッケージ 88 個）と Python の部品も検査されている（Green） |
| 4 | 直したイメージを `--ignore-unfixed` なしで検査：44 件（Debian の HIGH。`affected` 43・`fix_deferred` 1）で失敗。CI の引数では失敗しない |
| 5 | キャッシュが空で `--skip-db-update`：`--skip-db-update cannot be specified on the first run`、終了コード 1（素通りしない） |
| 6 | `--network none` で起動してスモークテストが通る（`/health` 200、`/daylight` 200、`/cloud-base` 502）。`id -u` は 10001、`/usr/local/bin` に pip はない |
| 7 | `Dockerfile.dev` をビルドし直して pytest 1796 件が通る（カバレッジ 99.59%）。nbmake 8 件が通る |
| 8 | ruff・ruff format・mypy・actionlint・zizmor（指摘なし、3 suppressed は #20 と同じ）・hadolint が通る（DL3059 は上のとおり直した） |
| 9 | 取り出した手順を `bash -e` で実行：直したイメージでは 0、直す前のイメージでは 1（CI・CD とも） |
| 10 | `docker buildx imagetools inspect` で、`python:3.14-slim`・`ghcr.io/astral-sh/uv:0.13.0`・`ghcr.io/aquasecurity/trivy:0.75.0` の digest が書いたものと一致（2026-10-16） |
| 11・12 | PR の CI と、マージ後の CD は人間が確認する |

- わざと壊す確認：pip を消す命令をなくす（＝直す前のイメージ）→ 1・9 で失敗する。`--exit-code 1` をなくす → 2 で素通りすることを確かめた（だから外さない）。`--ignore-unfixed` をなくす → 4 で、修正版のないものでも失敗するようになる。
