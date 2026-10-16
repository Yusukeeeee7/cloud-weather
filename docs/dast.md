# 動いている API への攻撃の検査（DAST。#23、Issue #45）

CD（`.github/workflows/cd.yml`）は、push の前に、起動した API に OWASP ZAP の API スキャンをかける。
`/openapi.json` に載っている道に、わざと変な入力（攻撃の形の入力）を送り、返ってきた応答を調べる。
**High の警告が 1 件でもあれば、CD は失敗し、push しない**。

| 手順 | やること |
|---|---|
| `Start container` | API を `--network none` で起動する（スモークテストと同じコンテナ） |
| `DAST (ZAP API scan)` | ZAP のコンテナを `--network container:api` で起動し、`zap-api-scan.py -t http://127.0.0.1:8000/openapi.json -f openapi` を実行。取り込んだ URL の数を確かめ、JSON のレポートを `scripts/zap_high_alerts.py` で読んで判定する |

- ZAP は API のコンテナのネットワークを共有するだけなので、`127.0.0.1` の API にしか届かない（外部と通信しない）。トークン・環境変数は渡さない。`docker login` より前に実行する。
- `zap-api-scan.py` は、重さに関係なくすべての警告を WARN（終了コード 2）にする。設定ファイル（`-c`）もルールの単位で、重さの単位では決められない。
  そこで、終了コード 0・2 は受け入れ、High の判定は JSON のレポートの `riskcode` で行う（`3` が High。ZAP のソースの `Alert.java` で `RISK_HIGH = 3`。WebFetch の要約で読んだ）。
  1（FAIL）・3（ZAP そのものの失敗）は CD の失敗にする。
- **ZAP は、定義から URL を取り込めなくても止まらない**（イメージの中の `zap-api-scan.py` の原文で確かめた。`Number of Imported URLs: N` をログに出すだけ）。しかも `/openapi.json` そのものを取りに行くので、レポートには API の site が残る。そこで CD の手順は、ZAP の出力の `Number of Imported URLs` が **8 以上**でなければ失敗にする（説明書を受け取っただけで、ボタンを押さないまま通さない）。8 は `/openapi.json` に載っている道の数（下の「初回の結果」）。道を減らしたら `cd.yml` の `min_imported_urls` を合わせる。道が 1 つもない定義を返す一時的なイメージでは、取り込まれた URL は 2 個で、この確認で失敗した（確認を足す前は、終了コード 0 で通っていた）。
- `scripts/zap_high_alerts.py` は、レポートが読めない・形が違う・API の site（`http://127.0.0.1:8000`）がないときも失敗にする。判定は、テストと同じ Python で動かすため、API のイメージの中で `--network none` で実行する（スモークテストと同じ形）。
  出すのは警告の ID・名前・件数だけで、URL や本文（`evidence` など）は出さない。
- レポートのフォルダ（`${RUNNER_TEMP}/zap`）は `chmod 777` にする。ZAP のイメージは `zap` ユーザー（uid 1000）で動き、runner のユーザーが作ったフォルダには書けないため（Linux のボリュームで、`chmod` なしでは `Permission denied` になることを手元で確かめた）。
- 除外の設定は `.zap/api-scan.conf`（`zap-api-scan.py -g` で作ったもの。すべて WARN）。直せない誤検知だけ、そのルールを IGNORE にし、理由をコメントに書く（1 件ずつ）。いまは除外していない。

## 使っているイメージ

- `ghcr.io/zaproxy/zaproxy:2.17.0@sha256:5ccfff9a411743ab2615136a2edd7416bec9ce41572fa94e935df38c14adb2b6`（正式版 v2.17.0。2025-12-15 公開）。
- **同じ `2.17.0` のタグは作り直される**（stable のイメージは月 1 回、add-on とベースを新しくして作り直される。公式ドキュメント「Docker」、WebFetch の要約で読んだ）。この digest のイメージは 2026-10-16 に作られたもの。digest で固定しているので、CD のイメージは勝手に変わらない。
- `docker run` のイメージなので、Dependabot は更新しない（Trivy と同じ）。上げるときは、手元で同じ手順を実行し、警告が増えないかを確かめてから digest を替える。
- **イメージに署名はない**（2026-10-16 に確かめた）。ZAP のリポジトリのイメージを公開するワークフロー（`release-main-docker.yml`・`release-weekly-docker.yml`・`release-live-docker.yml`）を `gh api` で取得して原文を検索し、cosign・Sigstore の手順がなく、`provenance: false` であることを見た。そのため、署名の検証はせず、digest の固定だけにしている。
- 手元でのイメージの大きさは 3.76GB（`docker images` の表示）。CD の取得に時間がかかる。

## 初回の結果（2026-10-16、手元で CD と同じ形で実行）

- High 0 件、Medium 0 件。CD の判定は通る。
- 取り込まれた URL は 11 個（ZAP の出力の `Number of Imported URLs`）。`/openapi.json` に載っている 8 つの道（`/health`・`/daylight`・`/weather`・`/cloud-base`・`/cloud-base/forecast`・`/cloud-base/history`・`/cloud-history`・`/sunshine`）すべてにスキャンが届いた。
- かかった時間は、このブランチのイメージで 73・266・269・269 秒（4 回）。CD のジョブの上限（20 分）に収まる。（わざと脆弱にしたイメージでは 279・280 秒。下の「High を検出できることの確認」）
- 1 回目のレポートは、判定スクリプトのテストの fixture として `tests/fixtures/zap/api_scan_2.17.0.json` に保存した。件数（ID の数ではなく、見つかった場所の数）は実行ごとに少し変わる。

| 重さ | 警告（ID） | 件数（1 回目のレポート） | 対応 |
|---|---|---|---|
| Low | A Server Error response code was returned by the server（100000） | 18 | **直さない**。すべて 502。外部と通信できないコンテナなので、Open-Meteo を呼ぶ道（`/weather`・`/cloud-base` など）が 502 を返すのは仕様どおり（`docs/spec.md` のエラー処理）。500（アプリの中の失敗）はなかった |
| Low | Unexpected Content-Type was returned（100001） | 2 | **直さない**。`/`（画面。#15）が HTML を返したもの。API の定義には載せていない道で、HTML を返すのが正しい |
| Low | X-Content-Type-Options Header Missing（10021） | 2 | **この Issue では直さない**。`/health`・`/openapi.json` の応答に `X-Content-Type-Options: nosniff` がない。spec にない仕様で、Low のため。全部の応答に付けるかは別の Issue の候補 |
| Informational | A Client Error response code was returned by the server（100000） | 17 | **直さない**。入力の検証（`city` の許可リストなど）で 422 を返したもの。仕様どおり |

## ZAP のログ（`zap.log`）のエラー

レポートの `insights` に `insight.log.error`（13 件）が出る。手元で 1 回、コンテナの中の `/home/zap/.ZAP/zap.log` を見た（2026-10-16。件数はこの回のもので、fixture の回の 13 件とは別の実行）。

| 行（重さ） | 件数 | 原因・対応 |
|---|---|---|
| `ExtensionCallHome - cfu.zaproxy.org`（ERROR） | 11 | ZAP が起動時に更新の確認（check for updates）に接続しようとして、名前を引けずに失敗した。外部と通信できないので想定どおり。スキャンには影響しない |
| `CommandLine - Check for updates call failed`（ERROR） | 2 | 同上 |
| `ExtensionCallHome - tel.zaproxy.org`（ERROR） | 2 | ZAP が利用データ（telemetry）を送ろうとして失敗した。CD では外部と通信できないので送られない |
| `RedirectScript - Failed to configure ZAP extension on browser launch`（WARN） | 11 | ブラウザを使うルールの準備に関するもの。原因は調べていない。ブラウザを使う DOM Based XSS（40026）は、下の確認で検出できている |
| `MacAddressUtil - Failed to find a usable hardware address`（WARN） | 1 | ネットワークの機器がないため。影響しない |

- ZAP は既定で `cfu.zaproxy.org`・`tel.zaproxy.org` に通信しようとする。手元で実行するときに外部と通信できる形にすると、これらに通信する。

## High を検出できることの確認

手元だけで、入力をそのまま HTML で返す道（`/echo?q=`）を足した一時的なイメージを作り、同じ手順を実行した（リポジトリには入れていない）。

- ZAP は `Cross Site Scripting (Reflected)`（40012）と `Cross Site Scripting (DOM Based)`（40026）を High として出した。
- 判定の手順は `NG: High [40012] ...`・`NG: High [40026] ...` を出し、終了コード 1 で失敗した（CD なら push しない）。
- API が動いていないとき（ZAP が `/openapi.json` を取れない）は、ZAP が終了コード 3 で終わり、手順も失敗した。

## 手元で実行する手順

Docker が要る。API と ZAP の両方を外部と通信できない形で動かす（Git Bash では `MSYS_NO_PATHCONV=1` を付ける）。

```bash
docker build --tag cloud-weather:cd .
docker run --detach --name api --network none cloud-weather:cd
mkdir -p zap-out && chmod 777 zap-out
docker run --rm --network container:api \
  --volume "$PWD/zap-out:/zap/wrk:rw" \
  --volume "$PWD/.zap:/zap/config:ro" \
  ghcr.io/zaproxy/zaproxy:2.17.0@sha256:5ccfff9a411743ab2615136a2edd7416bec9ce41572fa94e935df38c14adb2b6 \
  zap-api-scan.py -t http://127.0.0.1:8000/openapi.json -f openapi \
  -c /zap/config/api-scan.conf -J zap-report.json -s
python scripts/zap_high_alerts.py zap-out/zap-report.json   # 出力の Number of Imported URLs が 8 以上かも見る
docker rm --force api
```

- `zap-out/` はリポジトリに入れない（作業用のフォルダはリポジトリの外に作るとよい）。
- ZAP の終了コードは、警告があると 2 になる。判定は最後の `zap_high_alerts.py` の終了コードで見る。
