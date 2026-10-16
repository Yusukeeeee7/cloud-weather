# GitHub のセキュリティの設定（人間が設定画面で確かめた記録）

GitHub の設定は、コードやワークフローのファイルに残らない。人間が設定画面で見た状態を、ここに日付つきで記録する。
AI は設定画面を見られないので、人間のスクリーンショットをもとに書く。

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
