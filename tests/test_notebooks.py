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
