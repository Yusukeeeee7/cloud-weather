"""ZAP の API スキャンの JSON レポート（`-J`）を読み、High の警告があれば失敗にする（#23）。

ZAP の `zap-api-scan.py` は、重さに関係なくすべての警告を WARN として扱う。
「High なら push しない」を判定するために、レポートの `riskcode` を数える
（ZAP の Alert.java：0 Informational、1 Low、2 Medium、3 High）。

    python scripts/zap_high_alerts.py <レポートの JSON>

High が 1 件でもある、レポートが読めない・形が違う、API の site がないときは終了コード 1。
ZAP が定義から URL を取り込めたか（何も検査しないまま通らないか）は、このスクリプトでは見ない。
cd.yml の手順が ZAP の出力の「Number of Imported URLs」で確かめる。
警告の ID・名前・件数だけを出し、URL や本文（evidence など）は出さない。
"""

import json
import sys
from dataclasses import dataclass
from typing import Any

# CD で ZAP が問い合わせる API（scripts/smoke_test.py と同じ）。
TARGET_SITE = "http://127.0.0.1:8000"
RISK_NAMES = {"0": "Informational", "1": "Low", "2": "Medium", "3": "High"}
HIGH = "3"


class ReportError(Exception):
    pass


@dataclass(frozen=True)
class Alert:
    pluginid: str
    name: str
    riskcode: str
    count: int


def load_report(path: str) -> Any:
    try:
        with open(path, encoding="utf-8") as file:
            return json.load(file)
    except (OSError, ValueError) as error:
        raise ReportError(f"cannot read the report: {type(error).__name__}") from error


def parse_alerts(report: Any) -> list[Alert]:
    if not isinstance(report, dict) or not isinstance(report.get("site"), list):
        raise ReportError("the report has no site list")
    sites = report["site"]
    if not any(isinstance(site, dict) and site.get("@name") == TARGET_SITE for site in sites):
        raise ReportError(f"the report has no site {TARGET_SITE}")
    return [alert for site in sites for alert in parse_site(site)]


def parse_site(site: Any) -> list[Alert]:
    if not isinstance(site, dict) or not isinstance(site.get("alerts"), list):
        raise ReportError("a site has no alert list")
    return [parse_alert(alert) for alert in site["alerts"]]


def parse_alert(alert: Any) -> Alert:
    if not isinstance(alert, dict):
        raise ReportError("an alert is not an object")
    riskcode = alert.get("riskcode")
    if riskcode not in RISK_NAMES:
        raise ReportError(f"an alert has an unknown riskcode: {riskcode!r}")
    instances = alert.get("instances")
    count = len(instances) if isinstance(instances, list) else 0
    return Alert(
        pluginid=str(alert.get("pluginid")),
        name=str(alert.get("alert")),
        riskcode=riskcode,
        count=count,
    )


def summarize(alerts: list[Alert]) -> str:
    counts = {name: 0 for name in RISK_NAMES.values()}
    for alert in alerts:
        counts[RISK_NAMES[alert.riskcode]] += 1
    return ", ".join(f"{name}: {count}" for name, count in counts.items())


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: zap_high_alerts.py <report.json>", file=sys.stderr)
        return 1
    try:
        alerts = parse_alerts(load_report(argv[1]))
    except ReportError as error:
        print(f"NG: {error}", file=sys.stderr)
        return 1
    # 下の NG の行（標準エラー）より先に出るように、すぐ書き出す。
    print(f"ZAP alert types: {summarize(alerts)}", flush=True)
    high = [alert for alert in alerts if alert.riskcode == HIGH]
    for alert in high:
        print(f"NG: High [{alert.pluginid}] {alert.name} x {alert.count}", file=sys.stderr)
    return 1 if high else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
