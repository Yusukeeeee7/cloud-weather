# イメージの来歴と SBOM の検証（#22、Issue #43）

CD（`.github/workflows/cd.yml`）は、ghcr.io に push したイメージに 2 つの attestation（署名付きの書類）を付ける。

| 書類 | 中身 | 作る手順 |
|---|---|---|
| ビルドの来歴（provenance） | どのリポジトリの、どのワークフローで、どのコミットから作ったか（SLSA の形式） | `Attest provenance`（`actions/attest`） |
| SBOM | イメージの中の部品の一覧（SPDX 2.3 の JSON。Trivy で、検査に通ったのと同じ tar から作る） | `SBOM` → `Attest SBOM`（`actions/attest`） |

どちらも Sigstore の短い期間の証明書で署名され（鍵は持たない）、イメージの隣（同じ ghcr.io のパッケージ）に置かれる。
検証は、署名が本物か、書類が**この digest のイメージ**のものか、作ったのが**このリポジトリ**かを確かめる。

- 来歴が SLSA の形式なのは、`actions/attest` の README（v4.2.2）の「既定で SLSA build provenance を作る」による（WebFetch の要約で読んだ）。
- SBOM の文書の名前は、イメージ名ではなく `/scan/image.tar` になる（Trivy に tar を渡しているため）。部品の一覧には影響しない。
- push の後の digest の問い合わせや attest が失敗すると、署名のないイメージが push 済みになる（digest はレジストリから取るので、push の前には動かせない）。そのときは CD を再実行して付け直す。

## 使える条件（2026-10-16 に確かめた）

| 対象 | いまの状態 | 使えるか |
|---|---|---|
| リポジトリ | public | 使える。GitHub Free・Pro・Team では、artifact attestations は public のリポジトリだけで使える |
| リポジトリを private に戻したら | — | 使えない（GitHub Enterprise Cloud が要る）。CD の attest の手順が失敗する |
| パッケージ（ghcr.io） | private | 使える（attestation は同じ private のパッケージに置かれる）。検証する人は ghcr.io にログインが要る |

- 根拠：GitHub Docs「Artifact attestations」「Use artifact attestations」と `actions/attest` の README（WebFetch・検索の要約で読んだ。原文は読んでいない）。
- public のリポジトリの attestation は Sigstore の公開の透明性ログ（Rekor）に記録され、消せない（リポジトリ名・ワークフロー・コミット・イメージの digest が誰でも見える）。
- `actions/attest` の storage record は、組織のリポジトリでしか作れないので作らない（`create-storage-record: false`）。

## 手元から検証する手順

使う道具は GitHub CLI（`gh`）と Docker。

1. `gh` を入れて、ログインする。

   ```bash
   winget install --id GitHub.cli
   gh auth login
   ```

2. ghcr.io にログインする（パッケージが private なので、イメージの digest を調べるのに要る）。
   パスワードには、`read:packages` の権限を持つトークンを使う。

   ```bash
   docker login ghcr.io --username Yusukeeeee7
   ```

3. 来歴を検証する（タグは CD が付けた `sha-<短いSHA>` か `latest`）。

   ```bash
   gh attestation verify oci://ghcr.io/yusukeeeee7/cloud-weather:sha-<短いSHA> -R Yusukeeeee7/cloud-weather
   ```

4. SBOM を検証する。

   ```bash
   gh attestation verify oci://ghcr.io/yusukeeeee7/cloud-weather:sha-<短いSHA> -R Yusukeeeee7/cloud-weather \
     --predicate-type https://spdx.dev/Document/v2.3
   ```

5. 失敗することも確かめる（別のリポジトリを指定すると、attestation が見つからず失敗する。入口の確認で、署名が別のリポジトリのものだと見抜けることの確認にはならない）。

   ```bash
   gh attestation verify oci://ghcr.io/yusukeeeee7/cloud-weather:sha-<短いSHA> -R Yusukeeeee7/does-not-exist
   ```

- 3・4 は GitHub Docs の例（イメージの来歴、ファイルの SBOM）に沿った形。4 のように、イメージで `--predicate-type` を使う例は公式のページにない。1 回目の検証で動くかを確かめ、結果を下に書く。
- Git Bash で実行するときに引数が書き換えられて失敗したら、先頭に `MSYS_NO_PATHCONV=1` を付ける（#21 の cosign で起きた）。

## 検証の記録

人間が 1 回検証した結果を書く。

| 日付 | イメージ（タグと digest） | 手順 | 結果 |
|---|---|---|---|
| （未実施） | | 3 来歴 | |
| （未実施） | | 4 SBOM | |
| （未実施） | | 5 別のリポジトリ（見つからず失敗するはず） | |
