from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from ml.archive import parse_archive
from ml.dataset import build_dataset, join_hourly, load_dataset, save_dataset, validate_dataset
from ml.metar import parse_metar
from tests.ml.refs import CITIES, DATASET_COLUMNS, archive_text, metar_text


def _utc(text: str) -> pd.Timestamp:
    return pd.Timestamp(f"2025-01-15 {text}", tz="UTC")


def _weather(*times: str) -> pd.DataFrame:
    """手で書いた気象の表（正時）。値は行の番号。"""
    return pd.DataFrame(
        {
            "time": pd.to_datetime([_utc(text) for text in times], utc=True),
            "temperature_c": [float(index) for index in range(len(times))],
        }
    )


def _metar(*times: str) -> pd.DataFrame:
    """手で書いた METAR の表。`metar` に時刻の文字列を入れて、どの行が付いたか分かるようにする。"""
    return pd.DataFrame(
        {
            "station": ["XXXX"] * len(times),
            "observed_at": pd.to_datetime([_utc(text) for text in times], utc=True),
            "metar": list(times),
            "ceiling_m": [100.0 * (index + 1) for index in range(len(times))],
        }
    )


def _fixture_parts() -> dict[str, tuple[pd.DataFrame, pd.DataFrame]]:
    return {
        city: (parse_archive(archive_text(city)), parse_metar(metar_text(city))) for city in CITIES
    }


def _picked(joined: pd.DataFrame) -> list[str | None]:
    return [None if pd.isna(value) else value for value in joined["metar"]]


def test_join_picks_nearest_metar_within_30_minutes() -> None:
    weather = _weather("01:00", "02:00")
    metar = _metar("00:50", "01:20", "01:55")

    joined = join_hourly(weather, metar)

    assert _picked(joined) == ["00:50", "01:55"]


def test_join_one_row_per_hour() -> None:
    weather = _weather("00:00", "01:00", "02:00", "03:00")
    # 00:30 は 00:00 と 01:00 の両方から 30 分。行は増えない。
    metar = _metar("00:00", "00:30", "00:48", "01:00", "01:30", "02:00", "02:30", "03:00")

    joined = join_hourly(weather, metar)

    assert len(joined) == 4
    assert list(joined["time"]) == list(weather["time"])
    assert _picked(joined) == ["00:00", "01:00", "02:00", "03:00"]
    assert list(joined["temperature_c"]) == [0.0, 1.0, 2.0, 3.0]


@pytest.mark.parametrize(
    ("observed", "expected"),
    [
        # ちょうど 30 分は含める。
        (["00:30"], "00:30"),
        (["01:30"], "01:30"),
        # 同じ距離が 2 つあるときは、早いほう。
        (["00:30", "01:30"], "00:30"),
        (["00:45", "01:15"], "00:45"),
        # 近いほうが後ろにあれば、後ろ。
        (["00:40", "01:10"], "01:10"),
        # 30 分を超えるものは付けない。
        (["00:29", "01:31"], None),
        ([], None),
    ],
)
def test_join_boundary_30_minutes(observed: list[str], expected: str | None) -> None:
    joined = join_hourly(_weather("01:00"), _metar(*observed))

    assert _picked(joined) == [expected]


def test_join_just_outside_30_minutes_is_not_matched() -> None:
    joined = join_hourly(_weather("01:00"), _metar("00:29:59", "01:30:01"))

    assert _picked(joined) == [None]


def test_join_keeps_hours_without_metar() -> None:
    weather = _weather("00:00", "01:00", "02:00")
    metar = _metar("00:00", "02:10")

    joined = join_hourly(weather, metar)

    assert len(joined) == 3
    assert _picked(joined) == ["00:00", None, "02:10"]
    assert pd.isna(joined["ceiling_m"].iloc[1])
    assert pd.isna(joined["metar_observed_at"].iloc[1])
    assert list(joined["temperature_c"]) == [0.0, 1.0, 2.0]


def test_join_records_metar_time() -> None:
    joined = join_hourly(_weather("01:00", "02:00"), _metar("00:50", "02:20"))

    assert "observed_at" not in joined.columns
    assert "station" not in joined.columns
    assert list(joined["metar_observed_at"]) == [_utc("00:50"), _utc("02:20")]
    assert str(joined["metar_observed_at"].dt.tz) == "UTC"
    assert list(joined["ceiling_m"]) == [100.0, 200.0]


def test_join_does_not_depend_on_input_order() -> None:
    weather = _weather("01:00", "02:00")
    metar = _metar("00:50", "01:20", "01:55")

    joined = join_hourly(weather.iloc[::-1], metar.iloc[::-1])

    assert list(joined["time"]) == [_utc("01:00"), _utc("02:00")]
    assert _picked(joined) == ["00:50", "01:55"]


def test_join_rejects_naive_times() -> None:
    weather = _weather("01:00")
    metar = _metar("00:50")
    naive_weather = weather.assign(time=[datetime(2025, 1, 15, 1, 0)])
    naive_metar = metar.assign(observed_at=[datetime(2025, 1, 15, 0, 50)])

    with pytest.raises(ValueError):
        join_hourly(naive_weather, metar)
    with pytest.raises(ValueError):
        join_hourly(weather, naive_metar)


def test_join_rejects_non_utc_times() -> None:
    weather = _weather("01:00")
    tokyo_time = weather["time"].dt.tz_convert("Asia/Tokyo")

    with pytest.raises(ValueError):
        join_hourly(weather.assign(time=tokyo_time), _metar("00:50"))


def test_build_dataset_from_fixtures() -> None:
    dataset = build_dataset(_fixture_parts())

    assert list(dataset.columns) == DATASET_COLUMNS
    # 2 都市 × 48 時間（2025-01-15〜16）。
    assert len(dataset) == 96
    assert dataset.groupby("city").size().to_dict() == {"berlin": 48, "tokyo": 48}
    assert not dataset.duplicated(["city", "time"]).any()
    assert str(dataset["time"].dt.tz) == "UTC"
    validate_dataset(dataset)


def test_build_dataset_fixture_metar_is_within_30_minutes() -> None:
    dataset = build_dataset(_fixture_parts())

    matched = dataset.dropna(subset=["metar_observed_at"])
    distance = (matched["metar_observed_at"] - matched["time"]).abs()

    assert len(matched) > 0
    assert distance.max() <= pd.Timedelta(minutes=30)
    # 東京は毎時 0 分に報告があるので、正時の報告がそのまま付く。
    tokyo = matched[matched["city"] == "tokyo"]
    assert (tokyo["metar_observed_at"] == tokyo["time"]).all()
    # ベルリンは毎時 20 分・50 分なので、10 分前の報告が付く。
    # fixture の最初の正時だけは、前の報告が入っていないので 20 分後の報告になる。
    berlin = matched[matched["city"] == "berlin"]
    before = berlin["time"] - berlin["metar_observed_at"]
    assert len(berlin) == 48
    assert before.iloc[0] == pd.Timedelta(minutes=-20)
    assert (before.iloc[1:] == pd.Timedelta(minutes=10)).all()


def test_build_dataset_does_not_mix_cities() -> None:
    parts = _fixture_parts()
    tokyo_weather, tokyo_metar = parts["tokyo"]
    berlin_weather, berlin_metar = parts["berlin"]

    dataset = build_dataset(
        {"tokyo": (tokyo_weather, tokyo_metar), "berlin": (berlin_weather, berlin_metar.iloc[0:0])}
    )

    berlin = dataset[dataset["city"] == "berlin"]
    tokyo = dataset[dataset["city"] == "tokyo"]
    assert len(berlin) == 48
    assert berlin["metar"].isna().all()
    assert berlin["ceiling_m"].isna().all()
    assert tokyo["metar"].str.startswith("RJTT").all()


def test_build_dataset_is_deterministic_and_sorted() -> None:
    parts = _fixture_parts()
    reversed_parts = dict(reversed(list(parts.items())))

    first = build_dataset(parts)
    second = build_dataset(reversed_parts)

    pd.testing.assert_frame_equal(first, second)
    assert list(first["city"].unique()) == ["berlin", "tokyo"]
    for _, group in first.groupby("city"):
        assert group["time"].is_monotonic_increasing
    assert list(first.index) == list(range(len(first)))


def test_dataset_roundtrips_through_parquet(tmp_path: Path) -> None:
    dataset = build_dataset(_fixture_parts())
    path = tmp_path / "processed" / "observations.parquet"

    save_dataset(dataset, path)
    loaded = load_dataset(path)

    assert path.exists()
    pd.testing.assert_frame_equal(loaded, dataset)


def test_save_dataset_rejects_invalid_table(tmp_path: Path) -> None:
    dataset = build_dataset(_fixture_parts())
    path = tmp_path / "observations.parquet"

    with pytest.raises(ValueError):
        save_dataset(pd.concat([dataset, dataset.iloc[[0]]], ignore_index=True), path)

    assert not path.exists()


def test_validate_dataset_rejects_broken_tables() -> None:
    dataset = build_dataset(_fixture_parts())

    with pytest.raises(ValueError):
        validate_dataset(pd.concat([dataset, dataset.iloc[[0]]], ignore_index=True))
    with pytest.raises(ValueError):
        validate_dataset(dataset.drop(columns=["ceiling_m"]))
    with pytest.raises(ValueError):
        validate_dataset(dataset.iloc[::-1].reset_index(drop=True))
    with pytest.raises(ValueError):
        validate_dataset(dataset.iloc[0:0])
    with pytest.raises(ValueError):
        validate_dataset(dataset.assign(time=dataset["time"].dt.tz_localize(None)))
