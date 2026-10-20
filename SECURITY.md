# セキュリティポリシー

このリポジトリは、個人の学習用のプロジェクトです（1 人で開発・運用しています）。
脆弱性（セキュリティ上の問題）を見つけた方は、下の方法で非公開で知らせてください。

## 対象

- このリポジトリのコード：API（`app/`）、画面（`app/static/`）、`ml/`、ノートブック、`scripts/`、GitHub Actions のワークフロー、Dockerfile
- CD が ghcr.io に push するイメージの最新（`latest`）

古いイメージや過去のコミットは直しません。最新の main で直します。

## 報告の仕方

**公開の Issue・Pull Request・Discussions には書かないでください。**

GitHub の非公開の脆弱性報告を使ってください。

1. リポジトリの **Security** タブを開く
2. **Report a vulnerability** を押す
   （https://github.com/Yusukeeeee7/cloud-weather/security/advisories/new ）
3. 次のことを書く
   - どこで起きるか（ファイル、エンドポイント、ワークフローなど）
   - 再現の手順
   - 影響（何ができてしまうか）

報告の内容は、持ち主と管理者だけが見られます。

## 対象外

- 外部のサービス（Open-Meteo、IEM の METAR）そのものの問題は、それぞれの提供元に知らせてください。
- 依存パッケージそのものの脆弱性は、そのパッケージの提供元に知らせてください。
  このリポジトリでの使い方（古い版を使っている、危ない使い方をしている、など）の問題は対象です。

## 返事の目安

1 人で見ているため、目安です。

- 受け取ったことの返事：7 日以内
- 直すかどうかの判断を伝える：30 日以内

直した後、報告した方と相談して、GitHub の Security Advisory で内容を公開（開示）します。

## English

This is a personal learning project maintained by one person.

Please do not report security vulnerabilities through public issues, pull requests, or discussions.
Instead, report them privately via GitHub's private vulnerability reporting:
https://github.com/Yusukeeeee7/cloud-weather/security/advisories/new

We aim to acknowledge reports within 7 days and to share a decision within 30 days.
After a fix, we coordinate disclosure with the reporter through a GitHub Security Advisory.
