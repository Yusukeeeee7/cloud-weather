import copy
import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "zap_high_alerts.py"
# 手元で実際に ZAP を実行して得たレポート（High・Medium なし。tests/fixtures/README.md）。
REPORT_PATH = REPO_ROOT / "tests" / "fixtures" / "zap" / "api_scan_2.17.0.json"
TARGET_SITE = "http://127.0.0.1:8000"


def load_script() -> ModuleType:
    # scripts/ はパッケージではないので、ファイルの場所から読み込む。
    spec = importlib.util.spec_from_file_location("zap_high_alerts", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def script() -> ModuleType:
    return load_script()


@pytest.fixture
def report() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    return data


def write_report(tmp_path: Path, data: object) -> str:
    path = tmp_path / "zap-report.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def first_alert(report: dict[str, Any]) -> dict[str, Any]:
    alert: dict[str, Any] = report["site"][0]["alerts"][0]
    return alert


def test_fixture_is_the_expected_report(report: dict[str, Any]) -> None:
    # 前提の確認：実物のレポートは、API の site が 1 つで、High（3）・Medium（2）がない。
    assert [site["@name"] for site in report["site"]] == [TARGET_SITE]
    risks = {alert["riskcode"] for alert in report["site"][0]["alerts"]}
    assert risks == {"0", "1"}


def test_no_high_alerts_returns_0(
    script: ModuleType, capsys: pytest.CaptureFixture[str], report: dict[str, Any], tmp_path: Path
) -> None:
    assert script.main(["zap_high_alerts.py", write_report(tmp_path, report)]) == 0
    assert "High: 0" in capsys.readouterr().out


def test_high_alert_returns_1(
    script: ModuleType, capsys: pytest.CaptureFixture[str], report: dict[str, Any], tmp_path: Path
) -> None:
    alert = first_alert(report)
    alert["riskcode"] = "3"
    alert["riskdesc"] = "High (High)"

    assert script.main(["zap_high_alerts.py", write_report(tmp_path, report)]) == 1
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert alert["pluginid"] in output
    assert alert["alert"] in output
    assert "High: 1" in output


def test_medium_alert_is_not_high(
    script: ModuleType, report: dict[str, Any], tmp_path: Path
) -> None:
    for alert in report["site"][0]["alerts"]:
        alert["riskcode"] = "2"
        alert["riskdesc"] = "Medium (High)"

    assert script.main(["zap_high_alerts.py", write_report(tmp_path, report)]) == 0


def test_missing_file_returns_1(
    script: ModuleType, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    assert script.main(["zap_high_alerts.py", str(tmp_path / "missing.json")]) == 1
    assert "cannot read the report" in capsys.readouterr().err


def test_invalid_json_returns_1(
    script: ModuleType, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    path = tmp_path / "zap-report.json"
    path.write_text("{not json", encoding="utf-8")

    assert script.main(["zap_high_alerts.py", str(path)]) == 1
    assert "cannot read the report" in capsys.readouterr().err


def test_missing_argument_returns_1(script: ModuleType) -> None:
    assert script.main(["zap_high_alerts.py"]) == 1


@pytest.mark.parametrize(
    "data",
    [
        [],
        {},
        {"site": "not a list"},
        {"site": [{"@name": TARGET_SITE, "alerts": "not a list"}]},
        {"site": [{"@name": TARGET_SITE}]},
        {"site": [{"@name": TARGET_SITE, "alerts": [{"pluginid": "1", "alert": "x"}]}]},
    ],
)
def test_unexpected_shape_returns_1(script: ModuleType, tmp_path: Path, data: object) -> None:
    # 形が違うレポートを「High 0 件」として通さない。
    assert script.main(["zap_high_alerts.py", write_report(tmp_path, data)]) == 1


def test_empty_site_returns_1(script: ModuleType, report: dict[str, Any], tmp_path: Path) -> None:
    # ZAP が何も見ていない（site がない）のに通らない。
    report["site"] = []

    assert script.main(["zap_high_alerts.py", write_report(tmp_path, report)]) == 1


def test_no_target_site_returns_1(
    script: ModuleType, report: dict[str, Any], tmp_path: Path
) -> None:
    report["site"][0]["@name"] = "http://example.com"

    assert script.main(["zap_high_alerts.py", write_report(tmp_path, report)]) == 1


def test_output_does_not_include_evidence(
    script: ModuleType, capsys: pytest.CaptureFixture[str], report: dict[str, Any], tmp_path: Path
) -> None:
    alert = first_alert(report)
    alert["riskcode"] = "3"
    marker = "SECRET-LIKE-MARKER-1234"
    for instance in alert["instances"]:
        instance["uri"] = f"{TARGET_SITE}/{marker}"
        instance["evidence"] = marker
        instance["attack"] = marker
        instance["param"] = marker
        instance["otherinfo"] = marker
    alert["otherinfo"] = marker

    assert script.main(["zap_high_alerts.py", write_report(tmp_path, report)]) == 1
    captured = capsys.readouterr()
    assert marker not in captured.out
    assert marker not in captured.err


def test_other_site_without_high_returns_0(
    script: ModuleType, report: dict[str, Any], tmp_path: Path
) -> None:
    # API の site があれば、ほかの site が混じっていても失敗にしない（High がなければ 0）。
    other = copy.deepcopy(report["site"][0])
    other["@name"] = "http://example.com"
    report["site"].append(other)

    assert script.main(["zap_high_alerts.py", write_report(tmp_path, report)]) == 0


def test_high_alerts_on_other_sites_are_counted(
    script: ModuleType, report: dict[str, Any], tmp_path: Path
) -> None:
    other = copy.deepcopy(report["site"][0])
    other["@name"] = "http://example.com"
    other["alerts"][0]["riskcode"] = "3"
    report["site"].append(other)

    assert script.main(["zap_high_alerts.py", write_report(tmp_path, report)]) == 1
