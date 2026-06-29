from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import pandas as pd
import pytest
from lyra.sdk.context import RunContext
from lyra.sdk.models import FailedJobResult, JobEnvelope

from lyra_plugins.models.accessibility_jobs import JobGroupModel
from lyra_plugins.models.accessibility_services import AmenityGroupModel
from lyra_plugins.runners import (
    accessibility_jobs,
    accessibility_services,
    accessibility_services_with_public_spaces,
    temperature,
    temperature_raster,
    tree_coverage,
    tree_coverage_raster,
    urbanized_area,
)


@dataclass
class FakeContext:
    temp_dir: Path
    db: object | None = object()
    events: list[tuple[str, dict[str, object] | None]] = field(default_factory=list)

    def emit_event(self, event: str, data: dict[str, object] | None = None) -> None:
        self.events.append((event, data))

    def check_cancelled(self) -> None:
        return None


class FakeGeometryColumn:
    @property
    def iloc(self) -> "FakeGeometryColumn":
        return self

    def __getitem__(self, index: int) -> str:
        assert index == 0
        return "polygon"


class FakeGeoDataFrame:
    def to_crs(self, crs: str) -> "FakeGeoDataFrame":
        assert crs == "EPSG:4326"
        return self

    def __getitem__(self, key: str) -> FakeGeometryColumn:
        assert key == "geometry"
        return FakeGeometryColumn()


def _feature_collection() -> dict[str, object]:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "id": "area-1",
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [-99.20, 19.30],
                            [-99.10, 19.30],
                            [-99.10, 19.40],
                            [-99.20, 19.40],
                            [-99.20, 19.30],
                        ]
                    ],
                },
                "properties": {},
            },
            {
                "id": "area-2",
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [-99.30, 19.30],
                            [-99.20, 19.30],
                            [-99.20, 19.40],
                            [-99.30, 19.40],
                            [-99.30, 19.30],
                        ]
                    ],
                },
                "properties": {},
            },
        ],
        "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
    }


def _single_feature_collection() -> dict[str, object]:
    payload = _feature_collection()
    features = cast("list[object]", payload["features"])
    payload["features"] = [features[0]]
    return payload


def _job(metric: str, input_payload: Mapping[str, object]) -> JobEnvelope:
    return JobEnvelope.model_validate(
        {"job_id": f"job-{metric}", "metric": metric, "input": dict(input_payload)},
    )


def test_temperature_runner_returns_table_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_calculate(_data: object, *, year: int, season: str) -> dict[str, float]:
        assert year == 2025
        assert season == "spring"
        return {"area-1": 20.5, "area-2": 21.5}

    monkeypatch.setattr(temperature.temperature, "calculate", fake_calculate)
    result = temperature.run(
        _job(
            "temperature",
            {"location": _feature_collection(), "year": 2025, "season": "spring"},
        ),
        FakeContext(tmp_path),  # ty: ignore[invalid-argument-type]
    )

    assert result.job_id == "job-temperature"
    assert result.index == ["area-1", "area-2"]
    assert result.columns == ["temperature_c"]
    assert result.data == [[20.5], [21.5]]


def test_tree_coverage_runner_returns_table_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_calculate(_data: object) -> dict[str, float]:
        return {"area-1": 100.0, "area-2": 250.0}

    monkeypatch.setattr(tree_coverage, "calculate_tree_coverage", fake_calculate)
    result = tree_coverage.run(
        _job("tree_coverage", {"location": _feature_collection()}),
        FakeContext(tmp_path),  # ty: ignore[invalid-argument-type]
    )

    assert result.job_id == "job-tree_coverage"
    assert result.index == ["area-1", "area-2"]
    assert result.columns == ["tree_coverage_m2"]
    assert result.data == [[100.0], [250.0]]


def test_urbanized_area_runner_returns_table_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_calculate(_data: object) -> dict[str, float]:
        return {"area-1": 1000.0, "area-2": 2500.0}

    monkeypatch.setattr(urbanized_area, "calculate_urbanized_area", fake_calculate)
    result = urbanized_area.run(
        _job("urbanized_area", {"location": _feature_collection()}),
        FakeContext(tmp_path),  # ty: ignore[invalid-argument-type]
    )

    assert result.job_id == "job-urbanized_area"
    assert result.index == ["area-1", "area-2"]
    assert result.columns == ["urbanized_area_m2"]
    assert result.data == [[1000.0], [2500.0]]


def test_accessibility_jobs_uses_batch_key_for_columns_and_value_for_pattern(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    seen_patterns: list[str] = []

    def fake_prepare(
        _data: object,
        db: object,
        *,
        year: int,
        month: int | None,
    ) -> dict[str, object]:
        assert year == 2025
        assert month is None
        assert db is not None
        return {"prepared": True}

    def fake_for_items(
        item_key: str,
        item: JobGroupModel,
        **prepared: object,
    ) -> pd.DataFrame:
        assert prepared == {"prepared": True}
        assert item.edge_weights == "travel_time"
        assert item.max_weight == 2500
        assert item.network_type == "walk"
        seen_patterns.append(item.pattern)
        return pd.DataFrame(
            {f"jobs_{item_key}": [1.0 if item_key == "retail" else 2.0, 3.0]},
            index=["area-1", "area-2"],
        )

    monkeypatch.setattr(
        accessibility_jobs.accessibility_jobs, "calculate_prepare", fake_prepare
    )
    monkeypatch.setattr(
        accessibility_jobs.accessibility_jobs,
        "calculate_for_items",
        fake_for_items,
    )

    result = accessibility_jobs.run(
        _job(
            "accessibility_jobs",
            {
                "location": _feature_collection(),
                "patterns": [
                    {"key": "retail", "value": "^46.*", "label": "Retail"},
                    {"key": "education", "value": "^611.*"},
                ],
                "edge_weights": "travel_time",
                "max_weight": 2500,
                "network_type": "walk",
            },
        ),
        FakeContext(tmp_path),  # ty: ignore[invalid-argument-type]
    )

    assert not isinstance(result, FailedJobResult)
    assert seen_patterns == ["^46.*", "^611.*"]
    assert result.columns == ["jobs_retail", "jobs_education"]
    assert result.data == [[1.0, 2.0], [3.0, 3.0]]


def test_accessibility_jobs_rejects_duplicate_batch_keys(tmp_path: Path) -> None:
    result = accessibility_jobs.run(
        _job(
            "accessibility_jobs",
            {
                "location": _feature_collection(),
                "patterns": [
                    {"key": "retail", "value": "^46.*"},
                    {"key": "retail", "value": "^47.*"},
                ],
            },
        ),
        FakeContext(tmp_path),  # ty: ignore[invalid-argument-type]
    )

    assert isinstance(result, FailedJobResult)
    assert result.error["type"] == "validation"


def test_accessibility_jobs_returns_failed_result_without_db(tmp_path: Path) -> None:
    result = accessibility_jobs.run(
        _job(
            "accessibility_jobs",
            {
                "location": _feature_collection(),
                "patterns": [{"key": "retail", "value": "^46.*"}],
            },
        ),
        FakeContext(tmp_path, db=None),  # ty: ignore[invalid-argument-type]
    )

    assert isinstance(result, FailedJobResult)
    assert result.error["type"] == "configuration"


def test_accessibility_services_returns_failed_result_without_db(
    tmp_path: Path,
) -> None:
    result = accessibility_services.run(
        _job(
            "accessibility_services",
            {
                "location": _feature_collection(),
                "service_filters": [
                    {
                        "key": "parks",
                        "value": {"amenities": ["recreativo_parque"]},
                    }
                ],
            },
        ),
        FakeContext(tmp_path, db=None),  # ty: ignore[invalid-argument-type]
    )

    assert isinstance(result, FailedJobResult)
    assert result.error["type"] == "configuration"


def test_accessibility_services_uses_shared_settings_and_filter_amenities(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    seen_amenities: list[list[str]] = []

    def fake_prepare(
        _data: object,
        db: object,
        data_public: object | None = None,
        *,
        year: int,
        month: int | None,
    ) -> dict[str, object]:
        assert data_public is None
        assert year == 2024
        assert month == 11
        assert db is not None
        return {"prepared": True}

    def fake_for_items(
        item_key: str,
        item: AmenityGroupModel,
        **prepared: object,
    ) -> pd.Series:
        assert prepared == {"prepared": True}
        assert item.attraction_edge_weights == "travel_time"
        assert item.accessibility_edge_weights == "length"
        assert item.network_type == "drive"
        seen_amenities.append([amenity.value for amenity in item.amenities])
        return pd.Series(
            [0.25 if item_key == "health" else 0.75, 0.5],
            index=["area-1", "area-2"],
            name=f"accessibility_{item_key}",
        )

    monkeypatch.setattr(
        accessibility_services.accessibility_services,
        "calculate_prepare",
        fake_prepare,
    )
    monkeypatch.setattr(
        accessibility_services.accessibility_services,
        "calculate_for_items",
        fake_for_items,
    )

    result = accessibility_services.run(
        _job(
            "accessibility_services",
            {
                "location": _feature_collection(),
                "service_filters": [
                    {
                        "key": "health",
                        "value": {"amenities": ["salud_hospital"]},
                    },
                    {
                        "key": "parks",
                        "value": {"amenities": ["recreativo_parque"]},
                    },
                ],
                "attraction_edge_weights": "travel_time",
                "accessibility_edge_weights": "length",
                "network_type": "drive",
                "year": 2024,
                "month": 11,
            },
        ),
        FakeContext(tmp_path),  # ty: ignore[invalid-argument-type]
    )

    assert not isinstance(result, FailedJobResult)
    assert seen_amenities == [["salud_hospital"], ["recreativo_parque"]]
    assert result.columns == ["accessibility_health", "accessibility_parks"]
    assert result.data == [[0.25, 0.75], [0.5, 0.5]]


def test_accessibility_services_with_public_spaces_passes_public_input(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    seen_public_spaces: list[object | None] = []

    def fake_run_with_public_spaces(
        job: JobEnvelope,
        _context: RunContext,
        public_spaces: object | None,
    ) -> FailedJobResult:
        seen_public_spaces.append(public_spaces)
        return FailedJobResult(
            job_id=job.job_id,
            error={"type": "test", "message": "done"},
        )

    monkeypatch.setattr(
        accessibility_services_with_public_spaces,
        "run_with_public_spaces",
        fake_run_with_public_spaces,
    )

    result = accessibility_services_with_public_spaces.run(
        _job(
            "accessibility_services_with_public_spaces",
            {
                "location": _feature_collection(),
                "public_spaces": _feature_collection(),
                "service_filters": [
                    {
                        "key": "parks",
                        "value": {"amenities": ["recreativo_parque"]},
                    }
                ],
            },
        ),
        FakeContext(tmp_path),  # ty: ignore[invalid-argument-type]
    )

    assert isinstance(result, FailedJobResult)
    assert seen_public_spaces


def test_temperature_raster_writes_inside_context_temp_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_date_range(season: str, year: int) -> tuple[str, str]:
        assert season == "summer"
        assert year == 2025
        return ("2025-06-01", "2025-08-31")

    def fake_reduce(
        bounds: object,
        start_date: str,
        end_date: str,
        *,
        col_idx: int,
    ) -> str:
        assert bounds == "bounds"
        assert start_date == "2025-06-01"
        assert end_date == "2025-08-31"
        assert col_idx == 9
        return "img"

    def fake_download(
        img: object,
        bounds: object,
        fpath: Path,
        download_kwargs: dict[str, object],
    ) -> None:
        assert img == "img"
        assert bounds == "bounds"
        assert download_kwargs["scale"] == 30
        assert download_kwargs["crs"] == "EPSG:4326"
        fpath.write_bytes(b"data")

    monkeypatch.setattr(
        temperature_raster, "convert_geojson_to_gdf", lambda _data: FakeGeoDataFrame()
    )
    monkeypatch.setattr(
        temperature_raster, "convert_polygon_to_ee", lambda _polygon: "bounds"
    )
    monkeypatch.setattr(temperature_raster, "get_season_date_range", fake_date_range)
    monkeypatch.setattr(temperature_raster, "reduce_landsat_collection", fake_reduce)
    monkeypatch.setattr(temperature_raster, "download_ee_image", fake_download)

    result = temperature_raster.run(
        _job(
            "temperature_raster",
            {"bounds": _single_feature_collection(), "year": 2025, "season": "summer"},
        ),
        FakeContext(tmp_path),  # ty: ignore[invalid-argument-type]
    )

    path = Path(result.file_path)
    assert path == tmp_path / "temperature_raster.tif"
    assert path.read_bytes() == b"data"


def test_tree_coverage_raster_writes_inside_context_temp_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_download(
        img: object,
        bounds: object,
        fpath: Path,
        download_kwargs: dict[str, object],
    ) -> None:
        assert img == "img"
        assert bounds == "bounds"
        assert download_kwargs["scale"] == 10
        fpath.write_bytes(b"data")

    def fake_tree_image(_bounds: object, *, min_tree_height: object) -> str:
        assert min_tree_height == 3
        return "img"

    monkeypatch.setattr(
        tree_coverage_raster, "convert_geojson_to_gdf", lambda _data: FakeGeoDataFrame()
    )
    monkeypatch.setattr(
        tree_coverage_raster, "convert_polygon_to_ee", lambda _polygon: "bounds"
    )
    monkeypatch.setattr(
        tree_coverage_raster,
        "load_tree_coverage_fraction_img",
        fake_tree_image,
    )
    monkeypatch.setattr(tree_coverage_raster, "download_ee_image", fake_download)

    result = tree_coverage_raster.run(
        _job("tree_coverage_raster", {"bounds": _single_feature_collection()}),
        FakeContext(tmp_path),  # ty: ignore[invalid-argument-type]
    )

    path = Path(result.file_path)
    assert path == tmp_path / "tree_coverage_raster.tif"
    assert path.read_bytes() == b"data"
