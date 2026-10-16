import json
from pathlib import Path
from typing import Any

import pytest

from ml import model
from ml.features import FEATURE_NAMES

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
        # 出力に含まれてはいけない文字列。一時ファイルは作らない。
        "/tmp",  # noqa: S108
        "DISCORD_WEBHOOK",
        "password",
    ):
        assert word not in text
    assert "redis://" not in text.lower()
    # NaN・Infinity を含まない（JSON として正しい）。
    json.loads(text, parse_constant=lambda name: pytest.fail(f"unexpected constant: {name}"))


REPORTS_DIR = NOTEBOOKS_DIR.parent / "reports"
TRAINING_REPORT = REPORTS_DIR / "training.json"
METRICS_REPORT = REPORTS_DIR / "metrics.json"
MODEL_PATH = NOTEBOOKS_DIR.parent / "models" / "cloud_base.joblib"
MODEL_PREDICTIONS = ("model", *BASELINE_PREDICTIONS)
# docs/spec.md「9. 分割と評価」：学習 6 年と 3 年を、検証の年（2024）で比べる。
CANDIDATES = {
    "train_2018_2023": [2018, 2019, 2020, 2021, 2022, 2023],
    "train_2021_2023": [2021, 2022, 2023],
}
SUCCESS_KEYS = {
    "mae_improvement",
    "meets_mae",
    "mae_below_cap_improvement",
    "meets_mae_below_cap",
    "meets_both",
}


def _report(path: Path) -> dict[str, Any]:
    report: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return report


def _keys(value: Any) -> set[str]:
    """入れ子の中も含めた、すべてのキー。"""
    if isinstance(value, dict):
        return set(value) | {key for item in value.values() for key in _keys(item)}
    if isinstance(value, list):
        return {key for item in value for key in _keys(item)}
    return set()


def _assert_has_cities_and_seasons(report: dict[str, Any]) -> None:
    assert report["overall"]["n"] > 0
    assert isinstance(report["overall"]["mae_m"], float)
    assert sorted(report["by_city"]) == ["berlin", "tokyo"]
    for metrics in report["by_city"].values():
        assert metrics["n"] > 0
        assert isinstance(metrics["mae_m"], float)
        assert isinstance(metrics["mae_below_cap_m"], float)
    assert sorted(report["by_city_season"]) == ["berlin", "tokyo"]
    for seasons in report["by_city_season"].values():
        assert sorted(seasons) == ["autumn", "spring", "summer", "winter"]


def test_train_and_evaluate_notebooks_exist() -> None:
    assert NOTEBOOKS_DIR / "04_train.ipynb" in STRIPPED
    assert NOTEBOOKS_DIR / "05_evaluate.ipynb" in STRIPPED


def test_training_report_was_made_from_full_data() -> None:
    report = _report(TRAINING_REPORT)

    assert report["mode"] == "full"
    assert report["cap_m"] == 1524.0
    assert report["model_version"] == model.MODEL_VERSION_V1
    assert report["feature_names"] == list(FEATURE_NAMES)
    assert report["validation_years"] == [2024]
    # 6 年と 3 年の両方を、検証の年で評価している。
    candidates = report["candidates"]
    assert {name: candidate["train_years"] for name, candidate in candidates.items()} == CANDIDATES
    for candidate in candidates.values():
        assert candidate["n_train"] > 0
        assert candidate["best_iteration"] >= 1
        _assert_has_cities_and_seasons(candidate["validation"])
    assert report["selected"] in CANDIDATES
    assert list(report["validation_baselines"]) == list(BASELINE_PREDICTIONS)
    for baseline in report["validation_baselines"].values():
        _assert_has_cities_and_seasons(baseline)
    assert sorted(report["feature_importance"]) == sorted(FEATURE_NAMES)
    # テストの年（2025）は、学習の結果に入れない。
    assert "test" not in _keys(report)


def test_metrics_report_was_made_from_full_data() -> None:
    report = _report(METRICS_REPORT)

    assert report["mode"] == "full"
    assert report["cap_m"] == 1524.0
    assert {name: part["years"] for name, part in report["splits"].items()} == {
        "validation": [2024],
        "test": [2025],
    }
    for part in report["splits"].values():
        assert list(part["predictions"]) == list(MODEL_PREDICTIONS)
        for prediction in part["predictions"].values():
            _assert_has_cities_and_seasons(prediction)
    # 成功基準は、テストの年で、都市ごとに判定する。
    criteria = report["success_criteria"]
    assert sorted(criteria) == ["berlin", "tokyo"]
    for result in criteria.values():
        assert set(result) == SUCCESS_KEYS
        assert isinstance(result["mae_improvement"], float)
        assert isinstance(result["mae_below_cap_improvement"], float)
        assert isinstance(result["meets_both"], bool)
        assert result["meets_both"] == (result["meets_mae"] and result["meets_mae_below_cap"])


@pytest.mark.parametrize("path", [TRAINING_REPORT, METRICS_REPORT], ids=lambda path: path.name)
def test_reports_have_no_local_paths_or_secrets(path: Path) -> None:
    text = path.read_text(encoding="utf-8")

    for word in (
        "C:\\",
        "/home/",
        "/Users/",
        "/work",
        "/venv",
        # 出力に含まれてはいけない文字列。一時ファイルは作らない。
        "/tmp",  # noqa: S108
        "DISCORD_WEBHOOK",
        "password",
    ):
        assert word not in text
    assert "redis://" not in text.lower()
    # NaN・Infinity を含まない（JSON として正しい）。
    json.loads(text, parse_constant=lambda name: pytest.fail(f"unexpected constant: {name}"))


def _v1_model_path() -> Path:
    """v1（#11）のモデルのファイル。新しいモデルを採った後は、名前を変えて残す（#17）。"""
    if model.MODEL_VERSION == model.MODEL_VERSION_V1:
        return MODEL_PATH
    return MODEL_PATH.with_name("cloud_base_v1.joblib")


def test_v1_model_matches_current_features_and_reports() -> None:
    # 特徴量を変えたのにモデルを作り直していなければ、ここで気づく。
    loaded = model.load(_v1_model_path())
    training = _report(TRAINING_REPORT)

    assert loaded.feature_names == FEATURE_NAMES
    assert loaded.model_version == model.MODEL_VERSION_V1
    assert loaded.cap_m == 1524.0
    assert list(loaded.train_years) == CANDIDATES[training["selected"]]
    assert _report(METRICS_REPORT)["model_version"] == loaded.model_version


ERROR_ANALYSIS_REPORT = REPORTS_DIR / "error_analysis.json"
# docs/plans/16-error-analysis.md の質問 5：モデルと概算式の 2 つを並べる。
ERROR_ANALYSIS_PREDICTIONS = ("model", "rule_of_thumb")
HEIGHT_BANDS = ["0_300", "300_600", "600_1000", "1000_1524"]


def test_error_analysis_notebook_exists() -> None:
    assert NOTEBOOKS_DIR / "06_error_analysis.ipynb" in STRIPPED


def test_error_analysis_report_was_made_from_full_data() -> None:
    report = _report(ERROR_ANALYSIS_REPORT)

    assert report["mode"] == "full"
    assert report["cap_m"] == 1524.0
    assert report["years"] == [2024]
    assert report["model_version"] == model.MODEL_VERSION_V1
    assert report["model_version"] == _report(METRICS_REPORT)["model_version"]
    assert list(report["predictions"]) == list(ERROR_ANALYSIS_PREDICTIONS)
    for prediction in report["predictions"].values():
        assert prediction["overall"]["n_below_cap"] > 0
        assert sorted(prediction["by_city"]) == ["berlin", "tokyo"]
        for city in ("berlin", "tokyo"):
            assert prediction["by_city"][city]["n_below_cap"] > 0
            assert isinstance(prediction["by_city"][city]["mae_below_cap_m"], float)
            assert list(prediction["by_city_band"][city]) == HEIGHT_BANDS
            assert sorted(prediction["by_city_season"][city]) == [
                "autumn",
                "spring",
                "summer",
                "winter",
            ]
            for bands in prediction["by_city_season_band"][city].values():
                assert list(bands) == HEIGHT_BANDS


def test_error_analysis_report_matches_metrics_report() -> None:
    # 同じモデル・同じ検証の年なので、上限より下の行の数と MAE は 05 の結果と同じになる。
    report = _report(ERROR_ANALYSIS_REPORT)
    validation = _report(METRICS_REPORT)["splits"]["validation"]["predictions"]

    for name in ERROR_ANALYSIS_PREDICTIONS:
        for city in ("berlin", "tokyo"):
            ours, theirs = (
                report["predictions"][name]["by_city"][city],
                validation[name]["by_city"][city],
            )
            assert ours["n_below_cap"] == theirs["n_below_cap"]
            assert ours["mae_below_cap_m"] == theirs["mae_below_cap_m"]


def test_error_analysis_report_has_no_test_year() -> None:
    # docs/spec.md「9. モデルの改善」：#16 はテストの年（2025）を読まない。
    report = _report(ERROR_ANALYSIS_REPORT)

    assert "test" not in _keys(report)
    assert not any("2025" in key for key in _keys(report))
    assert 2025 not in report["years"]


def test_error_analysis_report_has_no_local_paths_or_secrets() -> None:
    text = ERROR_ANALYSIS_REPORT.read_text(encoding="utf-8")

    for word in (
        "C:\\",
        "/home/",
        "/Users/",
        "/work",
        "/venv",
        # 出力に含まれてはいけない文字列。一時ファイルは作らない。
        "/tmp",  # noqa: S108
        "DISCORD_WEBHOOK",
        "password",
    ):
        assert word not in text
    assert "redis://" not in text.lower()
    # NaN・Infinity を含まない（JSON として正しい）。
    json.loads(text, parse_constant=lambda name: pytest.fail(f"unexpected constant: {name}"))


# ここから下は #17（docs/plans/17-model-improvement.md）。
IMPROVEMENT_REPORT = REPORTS_DIR / "improvement.json"
METRICS_IMPROVED_REPORT = REPORTS_DIR / "metrics_improved.json"
CITY_NAMES = ("berlin", "tokyo")
# 「検証のしかた」：2 つの年で順に検証する。
IMPROVE_FOLDS = {
    "validation_2023": {
        "train_years": [2018, 2019, 2020, 2021, 2022],
        "validation_years": [2023],
    },
    "validation_2024": {
        "train_years": [2018, 2019, 2020, 2021, 2022, 2023],
        "validation_years": [2024],
    },
}
# 「比べる設定」の表（順も同じ）。
IMPROVE_SETTINGS = {
    "current": {"kind": "current", "below_cap_weight": None, "below_cap_threshold": None},
    "weighted_2": {"kind": "weighted", "below_cap_weight": 2.0, "below_cap_threshold": None},
    "weighted_4": {"kind": "weighted", "below_cap_weight": 4.0, "below_cap_threshold": None},
    "weighted_8": {"kind": "weighted", "below_cap_weight": 8.0, "below_cap_threshold": None},
    "two_stage_50": {"kind": "two_stage", "below_cap_weight": None, "below_cap_threshold": 0.5},
    "two_stage_40": {"kind": "two_stage", "below_cap_weight": None, "below_cap_threshold": 0.4},
    "two_stage_30": {"kind": "two_stage", "below_cap_weight": None, "below_cap_threshold": 0.3},
}
IMPROVE_BASELINES = ("rule_of_thumb", "always_cap")
IMPROVED_PREDICTIONS = ("model", "previous_model", "rule_of_thumb", "always_cap")
BY_CITY_KEYS = ("n", "mae_m", "n_below_cap", "mae_below_cap_m")


def _by_city(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """都市ごとの、行数と MAE（ほかの成果物と突き合わせる値）。"""
    return {
        city: {key: report["by_city"][city][key] for key in BY_CITY_KEYS} for city in CITY_NAMES
    }


def test_improve_notebooks_exist() -> None:
    assert NOTEBOOKS_DIR / "07_improve.ipynb" in STRIPPED
    assert NOTEBOOKS_DIR / "08_evaluate_improved.ipynb" in STRIPPED


def test_improvement_report_was_made_from_full_data() -> None:
    report = _report(IMPROVEMENT_REPORT)

    assert report["mode"] == "full"
    assert report["cap_m"] == 1524.0
    assert report["feature_names"] == list(FEATURE_NAMES)
    assert report["reference_model_version"] == model.MODEL_VERSION_V1
    assert report["folds"] == IMPROVE_FOLDS
    assert report["settings"] == IMPROVE_SETTINGS
    assert list(report["settings"]) == list(IMPROVE_SETTINGS)
    assert report["selection_rule"]["min_improvement"] == 0.1
    assert list(report["results"]) == list(IMPROVE_SETTINGS)
    for name, setting in IMPROVE_SETTINGS.items():
        assert list(report["results"][name]) == list(IMPROVE_FOLDS)
        for result in report["results"][name].values():
            assert result["n_train"] > 0
            assert result["best_iteration"] >= 1
            if setting["kind"] == "two_stage":
                assert result["best_iteration_classifier"] >= 1
            else:
                assert result["best_iteration_classifier"] is None
            _assert_has_cities_and_seasons(result["validation"])
            assert sorted(result["criteria"]) == list(CITY_NAMES)
            for criteria in result["criteria"].values():
                assert set(criteria) == SUCCESS_KEYS
                assert isinstance(criteria["mae_improvement"], float)
                assert isinstance(criteria["mae_below_cap_improvement"], float)
    assert list(report["validation_baselines"]) == list(IMPROVE_FOLDS)
    for baselines in report["validation_baselines"].values():
        assert list(baselines) == list(IMPROVE_BASELINES)
        for baseline in baselines.values():
            _assert_has_cities_and_seasons(baseline)


def test_improvement_report_selection_follows_the_rule() -> None:
    # 「選ぶ決まり」の 1〜4 が、ファイルの中の判定と合っている。
    report = _report(IMPROVEMENT_REPORT)
    selection = report["selection"]

    assert list(selection) == list(IMPROVE_SETTINGS)
    for name in IMPROVE_SETTINGS:
        judged = [
            criteria
            for result in report["results"][name].values()
            for criteria in result["criteria"].values()
        ]
        assert len(judged) == len(IMPROVE_FOLDS) * len(CITY_NAMES)
        assert selection[name]["eligible"] == all(item["meets_mae"] is True for item in judged)
        assert selection[name]["score"] == min(item["mae_below_cap_improvement"] for item in judged)
    current = selection["current"]["score"]
    eligible = {
        name: selection[name]["score"]
        for name in IMPROVE_SETTINGS
        if name != "current" and selection[name]["eligible"]
    }
    selected = report["selected"]
    if selected is None:
        # 値は小数 4 桁に丸めてある。選ばれていないなら、`current` を上回るものはない。
        assert all(score <= current for score in eligible.values())
    else:
        assert eligible[selected] == max(eligible.values())
        assert eligible[selected] >= current
        # 同じ点なら、表の上のもの。
        assert selected == next(name for name in eligible if eligible[name] == eligible[selected])


def test_improvement_report_reference_matches_training_report() -> None:
    # `current` は v1 と同じ設定・同じ年なので、04 の結果と同じになる。違えば環境か実装の誤り。
    ours = _report(IMPROVEMENT_REPORT)["results"]["current"]["validation_2024"]
    theirs = _report(TRAINING_REPORT)["candidates"]["train_2018_2023"]

    assert ours["n_train"] == theirs["n_train"]
    assert ours["best_iteration"] == theirs["best_iteration"]
    assert ours["validation"] == theirs["validation"]


def test_improvement_report_has_no_test_year() -> None:
    # docs/spec.md「9. モデルの改善」：案と設定を選ぶのに、テストの年（2025）を使わない。
    report = _report(IMPROVEMENT_REPORT)

    assert "test" not in _keys(report)
    assert not any("2025" in key for key in _keys(report))
    for fold in report["folds"].values():
        assert 2025 not in fold["train_years"]
        assert 2025 not in fold["validation_years"]


def test_metrics_improved_exists_only_when_a_setting_was_selected() -> None:
    # 「選ぶ決まり」の 4：選ばれた設定がなければ、テストの年は評価しない。
    selected = _report(IMPROVEMENT_REPORT)["selected"]

    assert METRICS_IMPROVED_REPORT.exists() == (selected is not None)


def test_metrics_improved_report_was_made_from_full_data() -> None:
    if not METRICS_IMPROVED_REPORT.exists():
        # テストの年に進まなかった（上のテストが、そのことを確かめている）。
        return
    report = _report(METRICS_IMPROVED_REPORT)

    assert report["mode"] == "full"
    assert report["cap_m"] == 1524.0
    assert report["model_version"] == model.MODEL_VERSION_V2
    assert report["previous_model_version"] == model.MODEL_VERSION_V1
    assert report["setting"] == _report(IMPROVEMENT_REPORT)["selected"]
    assert report["train_years"] == IMPROVE_FOLDS["validation_2024"]["train_years"]
    # 2025 年は #11 で 1 回見ている。
    assert report["test_year_evaluation"] == "second"
    assert list(report["predictions"]) == list(IMPROVED_PREDICTIONS)
    assert {name: part["years"] for name, part in report["splits"].items()} == {
        "validation": [2024],
        "test": [2025],
    }
    for part in report["splits"].values():
        assert list(part["predictions"]) == list(IMPROVED_PREDICTIONS)
        for prediction in part["predictions"].values():
            _assert_has_cities_and_seasons(prediction)
    assert report["success_criteria_split"] == "test"
    assert report["success_criteria_min_improvement"] == 0.1
    for name in ("success_criteria", "previous_success_criteria"):
        assert sorted(report[name]) == list(CITY_NAMES)
        for result in report[name].values():
            assert set(result) == SUCCESS_KEYS
            assert isinstance(result["meets_both"], bool)
            assert result["meets_both"] == (result["meets_mae"] and result["meets_mae_below_cap"])
    # 「選ぶ決まり」の 6：2 都市とも成功基準を満たしたときだけ採る。
    assert report["adopted"] is all(
        result["meets_both"] for result in report["success_criteria"].values()
    )


def test_metrics_improved_previous_model_matches_metrics_report() -> None:
    if not METRICS_IMPROVED_REPORT.exists():
        return
    # v1 の側は、同じモデル・同じ年なので、05 の結果と同じになる。
    ours, theirs = _report(METRICS_IMPROVED_REPORT), _report(METRICS_REPORT)

    assert ours["previous_model_version"] == theirs["model_version"]
    assert ours["previous_success_criteria"] == theirs["success_criteria"]
    for name in ("validation", "test"):
        for ours_label, theirs_label in (
            ("previous_model", "model"),
            ("rule_of_thumb", "rule_of_thumb"),
            ("always_cap", "always_cap"),
        ):
            assert (
                ours["splits"][name]["predictions"][ours_label]
                == theirs["splits"][name]["predictions"][theirs_label]
            )


def test_metrics_improved_validation_matches_improvement_report() -> None:
    if not METRICS_IMPROVED_REPORT.exists():
        return
    # 評価したのは、07 で選んだ設定の、`validation_2024` で学習したモデル。
    ours = _report(METRICS_IMPROVED_REPORT)
    improvement = _report(IMPROVEMENT_REPORT)
    theirs = improvement["results"][improvement["selected"]]["validation_2024"]["validation"]

    assert _by_city(ours["splits"]["validation"]["predictions"]["model"]) == _by_city(theirs)


def test_new_reports_have_no_local_paths_or_secrets() -> None:
    paths = [IMPROVEMENT_REPORT]
    if METRICS_IMPROVED_REPORT.exists():
        paths.append(METRICS_IMPROVED_REPORT)

    for path in paths:
        text = path.read_text(encoding="utf-8")
        for word in (
            "C:\\",
            "/home/",
            "/Users/",
            "/work",
            "/venv",
            # 出力に含まれてはいけない文字列。一時ファイルは作らない。
            "/tmp",  # noqa: S108
            "DISCORD_WEBHOOK",
            "password",
        ):
            assert word not in text
        assert "redis://" not in text.lower()
        # NaN・Infinity を含まない（JSON として正しい）。
        json.loads(text, parse_constant=lambda name: pytest.fail(f"unexpected constant: {name}"))


def test_served_model_matches_adoption() -> None:
    # API が読むファイル。採ったときだけ、新しいモデルに替わる。
    adopted = (
        METRICS_IMPROVED_REPORT.exists() and _report(METRICS_IMPROVED_REPORT)["adopted"] is True
    )
    loaded = model.load(MODEL_PATH)

    assert (model.MODEL_VERSION == model.MODEL_VERSION_V2) == adopted
    assert loaded.model_version == model.MODEL_VERSION
    assert loaded.feature_names == FEATURE_NAMES
    assert loaded.cap_m == 1524.0
    if adopted:
        report = _report(METRICS_IMPROVED_REPORT)
        assert loaded.model_version == report["model_version"]
        assert list(loaded.train_years) == report["train_years"]
    else:
        assert loaded.model_version == _report(METRICS_REPORT)["model_version"]
