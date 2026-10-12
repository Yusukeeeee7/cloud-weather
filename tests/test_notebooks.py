import json
from pathlib import Path

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
