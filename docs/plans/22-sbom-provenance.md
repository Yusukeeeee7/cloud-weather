# 計画：#22 SBOM と来歴（Issue #43）

状態：承認済み（2026-10-16、人間の回答「おすすめで進めてください」）

## 目的と受け入れ条件

spec.md「14. 機能一覧」より：

> | 22 | SBOM と来歴 | CD で push したイメージの SBOM を作り、ビルドの来歴をイメージに付ける。手元から来歴を検証する手順を docs に書き、人間が 1 回検証する。リポジトリやパッケージが private でも使えるかは計画で確かめる | 未着手 |

spec.md「11. セキュリティ要件」の共通の決まり（ツール・Action は理由を書いて承認を得る、SHA で固定、設定は公式ドキュメントで確かめる、通信先を書く、結果にシークレットを出さない）も守る。

たとえ：工場から出荷した箱（イメージ）に、2 枚の書類を**封をして（署名して）貼る**。

| 書類 | たとえ | この機能でやること |
|---|---|---|
| SBOM | 箱の中の部品表（どの部品が何個、どの版） | Trivy でイメージの部品表（SPDX の JSON）を作り、署名してイメージに付ける |
| 来歴（provenance） | 「どの工場の、どのライン（ワークフロー）で、どの設計図（コミット）から作ったか」の出荷証明 | GitHub の artifact attestation で作り、イメージに付ける |
| 検証 | 受け取った人が、封（署名）が本物で、書類が**この箱**のものかを確かめる | 手元で `gh attestation verify` を実行する手順を docs に書き、人間が 1 回実行する |

## 調べたこと（2026-10-16）

**1. GitHub の artifact attestations**（docs.github.com の「Artifact attestations」「Use artifact attestations」、`actions/attest` の README。どれも WebFetch の要約で読んだ。原文は読んでいない）：

- Action は `actions/attest`（最新 v4.2.2、2026-08-04 公開。コミットの SHA は実装時に取る）。`sbom-path` を付けないと**ビルドの来歴**、付けると **SBOM の attestation** になる（同じ Action を 2 回使う）。
- コンテナのイメージ：`subject-name` はタグなしのイメージ名（`ghcr.io/<owner>/cloud-weather`）、`subject-digest` は `sha256:<64桁>`、`push-to-registry: true` でレジストリ（イメージの隣）に attestation を置く。
- `sbom-path`：「JSON の SBOM（SPDX または CycloneDX）」。
- 必要な権限：`id-token: write`（Sigstore の証明書をもらう OIDC トークン）、`attestations: write`（attestation を保存）、`packages: write`（レジストリに置く。いまもある）。
- `create-storage-record`（既定 true）：**組織が持つリポジトリでしか作れない**。このリポジトリは個人の持ち物なので `false` にする（その場合 `artifact-metadata: write` の権限は要らない）。
- 検証：`docker login ghcr.io` のあと `gh attestation verify oci://ghcr.io/<owner>/<image>:<tag> -R <owner>/<repo>`。SBOM は `--predicate-type https://spdx.dev/Document/v2.3`（公式の例はファイルのみ。イメージで同じ引数が使えるかは実際に実行して確かめる）。

**2. private でも使えるか**（spec が求めている確認）：

| 対象 | いまの状態 | 使えるか | 根拠 |
|---|---|---|---|
| リポジトリ | public（#19 で記録） | **使える**。Free・Pro・Team のプランでは public のリポジトリだけ | 公式：「GitHub Free・Pro・Team のプランでは、artifact attestations は public のリポジトリだけで使える。private・internal で使うには GitHub Enterprise Cloud が要る」（検索の要約と `actions/attest` の README） |
| リポジトリを private に戻したら | — | **使えない**（Enterprise Cloud がないので、CD の attest の手順が失敗する） | 同上 |
| パッケージ（ghcr.io） | private（#14） | **使える**。attestation はイメージの隣（同じ private のパッケージ）に置かれる。検証する人は、パッケージを読めるログインが要る | 公式のページに、パッケージの公開・非公開による制限の記述はない。実装後に人間の検証で確かめる |

- public のリポジトリの attestation は、Sigstore の公開のインスタンスを使い、**公開の透明性ログ（Rekor）に記録される**（リポジトリ名・ワークフロー・コミット・イメージの digest が誰でも見える）。リポジトリが public なので、新しく知られる情報はイメージの digest くらい。

**3. SBOM を作る道具**：GitHub の公式ページは `anchore/sbom-action` を例に出しているが、**#21 で導入した Trivy（版と digest で固定済み）でも作れる**（trivy.dev の SBOM のページ：`--format spdx-json` / `--format cyclonedx`）。

**4. 手元で実行して確かめたこと**（Docker Desktop 29.6.2。いまの `Dockerfile` でビルドしたイメージ。リポジトリのファイルは変えていない。作ったファイルとイメージは消した）：

| 確かめたこと | 結果 |
|---|---|
| `docker save` の tar を、`--network none` の Trivy 0.75.0 で `image --input <tar> --format spdx-json --output <file>` | **終了コード 0。外部と通信せずに作れる**（脆弱性のデータベースも要らない。「`--format spdx-json` は検査を止める」と表示） |
| 出力 | `SPDX-2.3`、パッケージ 120 個。`fastapi`・`httpx`・`lightgbm` を含み、#21 で消した `pip` は含まない |
| 気になる表示 | `WARN Third-party SBOM may lead to inaccurate vulnerability detection`（イメージの中にほかの道具が作った SBOM のファイルがあるらしい。部品表を作るのには影響しない。実装時に出どころを確かめて記録する） |

## 今回やらないこと

- DAST（#23）、Scorecard（#24）
- **イメージを使う側（`notify.yml` や `docker compose`）で、毎回来歴を検証すること**（spec は「手元から 1 回」）
- SBOM をワークフローの成果物（artifact）として別に保存すること（attestation の中に入っている）
- SBOM に脆弱性の情報を入れること（`--scanners vuln`。脆弱性は #21 の手順が見る）
- `docker buildx` の自前の来歴・SBOM（`--provenance`・`--sbom`）に替えること（質問 2）
- CI（PR）で SBOM・来歴を作ること（push しないので付ける先がない）

## 変更・追加するファイル

| ファイル | 内容 |
|---|---|
| `.github/workflows/cd.yml` | ① ジョブの `permissions` に `id-token: write`・`attestations: write` を足す。② Trivy の手順の tar から SBOM を作る手順「SBOM」（`--network none`、`spdx-json`）。③ `Push image` で、push したイメージの digest を取り出して手順の出力にする。④ `actions/attest` を 2 回（来歴、SBOM）。`push-to-registry: true`、`create-storage-record: false`。⑤ `Log out of ghcr.io` は最後のまま |
| `docs/provenance.md`（新規） | 手元から来歴と SBOM を検証する手順（gh の入れ方、ログイン、コマンド、成功したときの表示）と、人間が 1 回検証した記録（日付・イメージのタグと digest・結果）。private で使えるかの表（上の「調べたこと」の 2） |
| `docs/spec.md` | #22 の状態、「13. CI/CD」の `cd.yml` の内容、「11. セキュリティ要件」に attestation の条件（リポジトリが public であること）を足す |

手順の並び（cd.yml）：

```
Docker build → Start container → Smoke test → Trivy DB → Trivy (image) → SBOM（新規。--network none）
→ Log in to ghcr.io → Push image（digest を出力）→ Attest provenance（新規）→ Attest SBOM（新規）→ Log out
```

- SBOM は**検査に通ったのと同じ tar** から作る（作り直さないイメージの部品表）。push より前に作るので、作れなければ push しない。
- digest の取り方は実装時に確かめる（候補：`docker push` のあとの `docker inspect --format '{{index .RepoDigests 0}}'`、または `docker buildx imagetools inspect`。main は 2 つのタグに同じイメージを push するので digest は 1 つのはず。必ず `sha256:` と 64 桁の 16 進数かを確かめてから渡す）。Actions のランナーの Docker の設定（containerd の image store かどうか）で、push される digest が変わることがある（リスク 2）。

## テスト一覧（先に書く順）

ワークフローの変更で、pytest の対象にならない（#19〜#21 と同じく、ツールを実行して確かめる）。来歴そのものは GitHub の Actions の上でしか作れない（OIDC のトークンが要る）ので、作る所は手元で試せない。

| # | 確認 | 種類（正常/異常/境界） | 確かめること |
|---|---|---|---|
| 1 | cd.yml の「SBOM」の `run:` を取り出し、#21 と同じく `RUNNER_TEMP` を作業用フォルダにして `bash -e` で実行 | 正常 | SPDX 2.3 の JSON ができ、`fastapi` があり `pip` がない（**Red にならない**。作る所の確認） |
| 2 | 1 で tar がない状態で実行 | 異常 | 0 以外で失敗する（SBOM が作れないのに push に進まない） |
| 3 | digest を取り出す部分を、`sha256:` 64 桁の値・空・おかしな値で実行（ローカルのレジストリは使わず、関数にした部分だけ試す） | 異常・境界 | 正しい値だけ通り、空・おかしな値では失敗する |
| 4 | actionlint・zizmor（#20 の CI と同じ引数） | 正常 | 権限の追加・新しい Action で指摘が出ない（出たら直すか 1 件ずつ理由を書いて除外） |
| 5 | `actions/attest` の SHA が v4.2.2 のタグのコミットであること（GitHub の API で照合） | 正常 | 固定した SHA が書いた版のもの |
| 6 | main へのマージ後に `cd.yml` が動く | 正常 | push の後に attest の 2 つの手順が成功し、要約（summary）に attestation が出る（人間が Actions の画面で確認） |
| 7 | 人間が手元で `gh attestation verify oci://ghcr.io/yusukeeeee7/cloud-weather:sha-<短いSHA> -R Yusukeeeee7/cloud-weather` | 正常 | 来歴の検証が成功する。表示（ワークフロー・コミット）を `docs/provenance.md` に記録 |
| 8 | 7 と同じく、`--predicate-type https://spdx.dev/Document/v2.3` を付けて検証 | 正常 | SBOM の検証が成功する |
| 9 | 7 を、別のリポジトリ（例：`-R Yusukeeeee7/存在しない名前`）を指定して実行 | 異常 | 失敗する（attestation が見つからないことの、入口の確認。署名が別のリポジトリのものだと見抜けることの確認にはならない。レビューで修正） |

- 6〜9 は AI から見えない・実行できないので、人間が行う。spec の状態は「実装済み（main へのマージ後の CD で確認）」→ 7〜9 の後に「完了」。

## 追加する依存パッケージ

Python の依存はなし。CI/CD と手元で使うものを足す（承認が要る。質問 1・3）：

| もの | 理由 | 代替案 |
|---|---|---|
| **`actions/attest` v4.2.2（コミットの SHA で固定）** | GitHub 公式の来歴・SBOM の attestation。Sigstore で署名し、イメージの隣に置ける。spec の「来歴をイメージに付ける」そのもの | `actions/attest-build-provenance`・`actions/attest-sbom`（公式の古い分け方。今の公式ページは `actions/attest`）、cosign で自分で署名（鍵の管理が増える） |
| SBOM は**新しく足さない**（#21 の Trivy を使う） | 導入済み・版と digest で固定済み・`--network none` で作れることを確かめた | `anchore/sbom-action`（公式ページの例。中で syft をダウンロードする所が 1 段増える） |
| **手元の `gh`（GitHub CLI）**（人間の PC に入れる。CI には入れない） | 来歴の検証の公式の道具。この PC には入っていない | cosign の公式イメージ（#21 で 1 回使った）。GitHub の attestation の形を cosign で検証する公式の手順は見つけていない |

## セキュリティ上の注意

- 入力検証：アプリの入力は変えない。digest は形（`sha256:` と 64 桁の 16 進数）を確かめてから Action に渡す。タグ名の検査（いまの正規表現）はそのまま。
- シークレット：鍵を持たない（Sigstore の短い期間の証明書を OIDC でもらう）。`GITHUB_TOKEN` は `actions/attest` が既定で使うものだけ。SBOM にシークレットが入らないこと（部品の名前と版だけ）を 1 で確かめる。
- 権限：`id-token: write`・`attestations: write` を cd のジョブにだけ足す（ワークフロー全体は `contents: read` のまま）。`id-token` を使えるのは Actions の手順で、`docker run` のコンテナ（スモークテスト・Trivy）には環境変数を渡さないので届かない（質問 4）。
- 外部通信：
  - `actions/attest`：Sigstore の公開のインスタンス（Fulcio・Rekor）、GitHub の API、ghcr.io。
  - SBOM の手順：`--network none`。
  - 手元の検証：GitHub の API、ghcr.io（`docker login` の情報を使う）、Sigstore の信頼の情報（TUF）。
- 公開される情報：Rekor にリポジトリ名・ワークフロー・コミット・イメージの digest が残る（消せない）。リポジトリは public なので、新しく知られるのは digest くらい。

## リスク・未決事項

1. **リポジトリを private に戻すと、CD が attest の手順で失敗する**（Enterprise Cloud がないため）。そのときは spec を見直す（spec と `docs/provenance.md` に書く）。
2. **push した digest の取り方**：Actions のランナーの Docker の image store の設定によって、`docker inspect` の値と、レジストリに置かれた digest がずれることがあるかもしれない。実装時は「push の出力に出た digest」と「レジストリの digest」が同じかを、最初の CD の実行で人間に確かめてもらう（6）。違えば検証（7）が失敗するので気づける。
3. `actions/attest` が個人のリポジトリで `create-storage-record: false` のとき正しく動くかは、README に書かれていない（「組織のリポジトリでしか作れない」とだけ）。最初の CD で確かめる。
4. Trivy の SBOM の `WARN Third-party SBOM`：イメージの中のどのファイルかを実装時に確かめる。
5. SBOM の検証（8）：公式の例はファイルだけ。イメージで `--predicate-type` が使えなければ、`--format json` で中身を見る手順に変える。
6. CD の時間が少し延びる（SBOM の生成で 1 分ほど）。`timeout-minutes: 20` で足りるかは実行時間を見る。

## ブロッカー（人間の対応が必要なこと）

- 手元の検証（7〜9）のため、人間の PC に `gh` を入れ、`gh auth login` する必要がある（質問 3）。
- 必要な外部 API の項目はない。

## 質問

未回答：なし

回答済み（2026-10-16、人間の回答「おすすめで進めてください」）：

- 質問 1：`actions/attest` v4.2.2 を SHA で固定して導入する。`create-storage-record: false`。
- 質問 2：A。`actions/attest` で来歴を作る。
- 質問 3：A。人間の PC に `gh` を入れて検証する。
- 質問 4：A。同じジョブ（`cd`）で attest する。
- 質問 5：SPDX（`spdx-json`）。
- 質問 6：ブランチは `feature/issues_43`。

以下は、レビューのときに示した質問の原文。

1. **`actions/attest`（v4.2.2、SHA で固定）の導入を承認するか**。来歴と SBOM の 2 回使う。`create-storage-record: false`。
2. **来歴の作り方**：
   - **A（おすすめ）：`actions/attest`**（GitHub の attestation）。いまの「テストしたイメージを作り直さずに push」の形のまま、push した digest に付けられる。検証は `gh attestation verify`。
   - B：`docker buildx build --provenance --sbom`（BuildKit の来歴）。ビルドと push が同じ命令になるので、「テストしたイメージに付けて push」の形を変える必要がある。署名は別に要る。
3. **手元の検証の道具**：
   - **A（おすすめ）：人間の PC に `gh` を入れる**（winget の `GitHub.cli`）。公式の検証の手順そのもの。メモにある「gh がない」は、この PC の状態が変わる。
   - B：cosign の公式イメージで検証する手順を探す（公式の手順は見つけていない。見つからなければ A に戻る）。
4. **attest を同じジョブで行うか**：
   - **A（おすすめ）：同じジョブ**（`cd`）。SBOM の tar と digest をそのまま使える。`id-token` は Actions の手順にしか届かない。
   - B：別のジョブに分ける（`id-token` を持つジョブを、スモークテスト・Trivy のコンテナを動かすジョブから離せる）。SBOM を渡すため `actions/upload-artifact`・`download-artifact` が増える。
5. **SBOM の形式**：**おすすめは SPDX（`spdx-json`）**。GitHub の検証の例が SPDX 2.3 の `--predicate-type` を使っている。CycloneDX でもよい。
6. **ブランチ名**：`feature/issues_43`（Issue 番号）でよいか。

## 実装時の変更

- **digest の取り方は `docker buildx imagetools inspect <イメージ:タグ> --format '{{.Manifest.Digest}}'` にした**（計画の候補の 2 つ目）。push の後にレジストリへ問い合わせるので、ランナーの Docker の image store の設定によらず、レジストリに置かれた digest が取れる（リスク 2 への対応）。手元で `ghcr.io/aquasecurity/trivy:0.75.0` に実行し、#21 で固定した digest と一致することを確かめた。取った値は `^sha256:[0-9a-f]{64}$` で確かめ、イメージ名と一緒に `GITHUB_OUTPUT` に書く。
- `actions/attest` の SHA：`1e69f48acb82d1966a394da916b4c1698aa569d6`（GitHub の API `repos/actions/attest/git/ref/tags/v4.2.2` で、v4.2.2 のタグが指すコミットと照合。WebFetch で取得）。`action.yml`（v4.2.2）の入力（`subject-name`・`subject-digest`・`sbom-path`・`push-to-registry`・`create-storage-record`）は WebFetch の要約で確かめた。
- 手元の確認は、`cd.yml` から手順の `run:` の本文を awk で取り出し、`bash -e` で実行した（#21 と同じやり方。スクリプトは作業用フォルダに置き、リポジトリには入れない）。「Push image」の確認では、`docker` を何もしない関数に置き換え、`imagetools inspect` だけ決めた digest を返すようにした。
- リスク 4 の `WARN Third-party SBOM` の出どころ：`/app/.venv/lib/python3.14/site-packages/scipy-1.18.1.dist-info/sboms/auditwheel.cdx.json`（scipy の wheel に同梱された、wheel に入れた共有ライブラリの部品表）。部品表を作るのには影響しない。
- 検証の手順の 2（ghcr.io へのログイン）は、`read:packages` の権限を持つトークンを使う形にした。`gh` のトークンで足りるかは確かめていない（人間の 1 回目の検証で確かめる）。

### テストの結果

| # | 結果 |
|---|---|
| 1 | SPDX-2.3、パッケージ 120 個。`fastapi` あり、`pip` なし（Red のときは「手順がない」で失敗） |
| 2 | tar がないと 0 以外で失敗する |
| 3 | 正しい digest で `name=ghcr.io/yusukeeeee7/cloud-weather`・`digest=sha256:...` が出力される。空・`sha256:abc`・大文字・`sha512:`・後ろに余計な文字、の 5 つで失敗する（Red のときは 6 つとも失敗） |
| 4 | actionlint 終了コード 0。zizmor「No findings」（3 suppressed は #20 と同じ） |
| 5 | SHA は v4.2.2 のタグのコミット（上のとおり） |
| — | ruff・ruff format・mypy が通る。pytest 1796 件が通る（カバレッジ 99.59%。Python は変えていない） |
| 6 | PR #44 のマージ後の CD（run 38925065692）がすべて成功。push の出力の digest と attestation の digest が同じ（リスク 2 は問題なし）。`create-storage-record: false` で動いた（リスク 3） |
| 7〜9 | 2026-10-16、人間がログインした PC で AI が実行。7・8 は成功（8 はイメージでも `--predicate-type` が使えた。リスク 5）、9 は 404 で失敗（予想どおり）。詳細は `docs/provenance.md` の「検証の記録」 |

- わざと壊す確認（写した `cd.yml` で 1 か所ずつ。リポジトリのファイルは変えていない）：digest の確認をなくす → 3 の 5 件で検出。`--format cyclonedx` にする → 1 で検出。`name=` の出力をなくす → 3 で検出。正規表現の末尾の `$` をなくす → 「後ろに余計な文字」で検出。
