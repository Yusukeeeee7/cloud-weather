import json
from pathlib import Path
from typing import Any

import pytest

NOTEBOOKS_DIR = Path(__file__).parent.parent / "notebooks"
# 02_eda.ipynb だけは、出力を残してコミットする（CLAUDE.md「ノートブック」）。
KEEPS_OUTPUTS = {"02_eda.ipynb"}
STRIPPED = sorted(path for path in NOTEBOOKS_DIR.glob("*.ipynb") if path.name not in KEEPS_OUTPUTS)


def test_data_fetch_notebook_exists() -> None:
    assert NOTEBOOKS_DIR / "01_data_fetch.ipynb" in STRIPPED


@pytest.mark.parametrize("path", STRIPPED, ids=lambda path: path.name)
def test_notebook_has_no_outputs(path: Path) -> None:
    notebook = json.loads(path.read_text(encoding="utf-8"))

    code_cells = [cell for cell in notebook["cells"] if cell["cell_type"] == "code"]
    assert code_cells
    for cell in code_cells:
        assert cell["outputs"] == []
        assert cell["execution_count"] is None


@pytest.mark.parametrize("path", STRIPPED, ids=lambda path: path.name)
def test_notebook_does_not_contain_local_paths_or_secrets(path: Path) -> None:
    text = path.read_text(encoding="utf-8")

    for word in ("C:\\\\Users", "/home/", "/Users/", "DISCORD_WEBHOOK", "password"):
        assert word not in text


EDA_NOTEBOOK = NOTEBOOKS_DIR / "02_eda.ipynb"


def _eda_code_cells() -> list[dict[str, Any]]:
    notebook = json.loads(EDA_NOTEBOOK.read_text(encoding="utf-8"))
    return [cell for cell in notebook["cells"] if cell["cell_type"] == "code"]


def _output_texts(cell: dict[str, Any]) -> list[str]:
    """セルの出力のうち、文字として読める部分（画像は含めない）。"""
    texts: list[str] = []
    for output in cell["outputs"]:
        texts.append("".join(output.get("text", [])))
        for kind, value in output.get("data", {}).items():
            if kind.startswith("text/"):
                texts.append("".join(value))
    return texts


def test_eda_notebook_exists() -> None:
    assert EDA_NOTEBOOK.exists()
    assert EDA_NOTEBOOK.name in KEEPS_OUTPUTS


def test_eda_notebook_keeps_outputs() -> None:
    cells = _eda_code_cells()

    # 上から順に 1 回ずつ実行した状態（途中から実行し直した状態でコミットしない）。
    assert [cell["execution_count"] for cell in cells] == list(range(1, len(cells) + 1))
    outputs = [output for cell in cells for output in cell["outputs"]]
    assert outputs
    assert all(output["output_type"] != "error" for output in outputs)
    assert any("image/png" in output.get("data", {}) for output in outputs)
    # 実行した時刻は残さない（再実行のたびに差分が出るため）。
    assert all("execution" not in cell["metadata"] for cell in cells)


def test_eda_notebook_outputs_have_no_local_paths_or_secrets() -> None:
    cells = _eda_code_cells()
    texts = [text for cell in cells for text in ["".join(cell["source"]), *_output_texts(cell)]]

    assert texts
    for text in texts:
        for word in ("C:\\", "/home/", "/Users/", "/work", "/venv", "DISCORD_WEBHOOK", "password"):
            assert word not in text
        assert "redis://" not in text.lower()


def test_eda_notebook_was_run_on_full_data() -> None:
    # 設定のセルが `mode=<sample|full>` を表示する。コミットするのは全期間の出力。
    lines = [
        line
        for cell in _eda_code_cells()
        for text in _output_texts(cell)
        for line in text.splitlines()
        if line.startswith("mode=")
    ]

    assert lines == ["mode=full"]


BASELINE_REPORT = NOTEBOOKS_DIR.parent / "reports" / "baseline.json"
# 成功基準を決める前にテストの年（2025）の数値を見ない（docs/plans/10-baseline.md の質問 3）。
BASELINE_SPLITS = ("train", "validation")
BASELINE_PREDICTIONS = ("rule_of_thumb", "always_cap", "rule_of_thumb_metar")


def _baseline_report() -> dict[str, Any]:
    report: dict[str, Any] = json.loads(BASELINE_REPORT.read_text(encoding="utf-8"))
    return report


def test_baseline_notebook_exists() -> None:
    assert NOTEBOOKS_DIR / "03_baseline.ipynb" in STRIPPED


def test_baseline_report_was_made_from_full_data() -> None:
    report = _baseline_report()

    # コミットするのは全期間の結果。上限は docs/spec.md「9. 目的変数」の 1,524 m。
    assert report["mode"] == "full"
    assert report["cap_m"] == 1524.0
    assert list(report["splits"]) == list(BASELINE_SPLITS)
    for split in BASELINE_SPLITS:
        predictions = report["splits"][split]["predictions"]
        assert list(predictions) == list(BASELINE_PREDICTIONS)
        for name in BASELINE_PREDICTIONS:
            assert predictions[name]["overall"]["n"] > 0
            by_city = predictions[name]["by_city"]
            assert sorted(by_city) == ["berlin", "tokyo"]
            for metrics in by_city.values():
                assert metrics["n"] > 0
                assert isinstance(metrics["mae_m"], float)
                assert isinstance(metrics["mae_below_cap_m"], float)
            assert sorted(predictions[name]["by_city_season"]) == ["berlin", "tokyo"]
            for seasons in predictions[name]["by_city_season"].values():
                assert sorted(seasons) == ["autumn", "spring", "summer", "winter"]


def test_baseline_report_has_no_test_year_local_paths_or_secrets() -> None:
    text = BASELINE_REPORT.read_text(encoding="utf-8")

    assert "test" not in _baseline_report()["splits"]
    for word in (
        "C:\\",
        "/home/",
        "/Users/",
        "/work",
        "/venv",
        "/tmp",
        "DISCORD_WEBHOOK",
        "password",
    ):
        assert word not in text
    assert "redis://" not in text.lower()
    # NaN・Infinity を含まない（JSON として正しい）。
    json.loads(text, parse_constant=lambda name: pytest.fail(f"unexpected constant: {name}"))
