import importlib
from collections.abc import Iterator
from typing import TypeVar
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from geopandas.testing import assert_geodataframe_equal
from lyra.sdk import (
    LocationInput,
    MetricInputError,
    MetricParameters,
    MetricResultError,
)
from lyra.utils.geometry import convert_geojson_to_gdf
from pandas.testing import assert_frame_equal

from lyra_plugins import definitions
from lyra_plugins.metrics.temperature import common as temperature_common
from lyra_plugins.metrics.temperature import table as temperature_workflow
from lyra_plugins.metrics.tree_coverage import common as tree_common
from lyra_plugins.metrics.tree_coverage import table as tree_workflow
from lyra_plugins.metrics.urbanization import common as urbanization_common
from lyra_plugins.metrics.urbanization import urbanization_year_table as year_workflow
from lyra_plugins.metrics.urbanization import urbanized_area_table as area_workflow

ParametersT = TypeVar("ParametersT", bound=MetricParameters)


def expect_equal(actual: object, expected: object) -> None:
    if actual != expected:
        raise AssertionError((actual, expected))


def prepare(
    name: str, values: dict[str, object], model: type[ParametersT]
) -> ParametersT:
    parameters = definitions.create_plugin().prepare_parameters(name, values)
    if not isinstance(parameters, model):
        raise TypeError(type(parameters))
    return parameters


@pytest.fixture
def location() -> LocationInput:
    # Deliberately nonlexical IDs, different polygon sizes, and a projected CRS.
    features = []
    for identifier, x, width in [("zone-z9", 0, 300), ("zone-a2", 1000, 100)]:
        ring = [[x, 0], [x + width, 0], [x + width, 100], [x, 100], [x, 0]]
        geometry = (
            {"type": "Polygon", "coordinates": [ring]}
            if identifier == "zone-z9"
            else {"type": "MultiPolygon", "coordinates": [[ring]]}
        )
        features.append(
            {
                "type": "Feature",
                "id": identifier,
                "properties": {"label": identifier},
                "geometry": geometry,
            }
        )
    return LocationInput.model_validate(
        {
            "type": "FeatureCollection",
            "crs": {"type": "name", "properties": {"name": "EPSG:3857"}},
            "features": features,
        }
    )


@pytest.fixture(autouse=True)
def no_authentication() -> Iterator[None]:
    with (
        patch("ee.Initialize", side_effect=AssertionError("Unexpected initialization")),
        patch(
            "ee.Authenticate", side_effect=AssertionError("Unexpected authentication")
        ),
    ):
        yield


@pytest.mark.parametrize("missing", [False, True])
def test_temperature_matches_original(
    location: LocationInput, *, missing: bool
) -> None:
    parameters = prepare(
        "temperature",
        {"year": 2024, "season": "winter"},
        definitions.TemperatureParameters,
    )
    raw = pd.Series([None if missing else 18.5, 26.75], index=["zone-a2", "zone-z9"])
    gdf = convert_geojson_to_gdf(location)
    with (
        patch.object(temperature_workflow, "ee") as earth,
        patch.object(temperature_workflow, "load_temperature_img") as load,
        patch.object(
            temperature_workflow, "reduce_ee_image_over_gdf", return_value=raw
        ) as reduce,
    ):
        original = temperature_workflow.calculate_temperature_table(gdf, 2024, "winter")
        frame = definitions.temperature(location, parameters)
        load.assert_called_with(
            earth.Geometry.BBox.return_value, "2023-12-01", "2024-02-29", col_idx=9
        )
        expect_equal(reduce.call_args.kwargs["scale"], 30)
        expect_equal(
            reduce.call_args.kwargs["reducer"], earth.Reducer.mean.return_value
        )
        assert_geodataframe_equal(reduce.call_args.args[0], gdf.to_crs("EPSG:4326"))
    assert_frame_equal(frame, original.reindex(gdf.index).to_frame("temperature_c"))
    result = definitions.create_plugin().normalize_result(
        "temperature", frame, job_id="local-test", location=location
    )
    expect_equal(result.model_dump()["data"], [[26.75], [None if missing else 18.5]])


@pytest.mark.parametrize("missing", [False, True])
def test_tree_coverage_matches_original(
    location: LocationInput, *, missing: bool
) -> None:
    parameters = prepare(
        "tree_coverage", {"min_tree_height": 3}, definitions.TreeCoverageParameters
    )
    raw = pd.Series([None if missing else 120.0, 450.0], index=["zone-a2", "zone-z9"])
    gdf = convert_geojson_to_gdf(location)
    with (
        patch.object(tree_workflow, "ee") as earth,
        patch.object(tree_workflow, "load_tree_coverage_area_img") as load,
        patch.object(
            tree_workflow, "reduce_ee_image_over_gdf", return_value=raw
        ) as reduce,
    ):
        original = tree_workflow.calculate_tree_coverage_table(gdf, 3)
        frame = definitions.tree_coverage(location, parameters)
        load.assert_called_with(earth.Geometry.BBox.return_value, min_tree_height=3)
        expect_equal(reduce.call_args.kwargs["scale"], 1)
        expect_equal(reduce.call_args.kwargs["reducer"], earth.Reducer.sum.return_value)
        assert_geodataframe_equal(reduce.call_args.args[0], gdf.to_crs("EPSG:4326"))
    assert_frame_equal(frame, original.reindex(gdf.index).to_frame("tree_coverage_m2"))
    result = definitions.create_plugin().normalize_result(
        "tree_coverage", frame, job_id="local-test", location=location
    )
    expect_equal(result.model_dump()["data"], [[450.0], [None if missing else 120.0]])


@pytest.mark.parametrize("missing", [False, True])
def test_urbanized_area_matches_original(
    location: LocationInput, *, missing: bool
) -> None:
    parameters = prepare(
        "urbanized_area", {"year": 2020}, definitions.UrbanizedAreaParameters
    )
    raw = pd.Series([None if missing else 700.0, 1800.0], index=["zone-a2", "zone-z9"])
    gdf = convert_geojson_to_gdf(location)
    with (
        patch.object(area_workflow, "ee") as earth,
        patch.object(area_workflow, "load_urbanized_area_img") as load,
        patch.object(
            area_workflow, "reduce_ee_image_over_gdf", return_value=raw
        ) as reduce,
    ):
        original = area_workflow.calculate_urbanized_area_table(gdf, 2020)
        frame = definitions.urbanized_area(location, parameters)
        load.assert_called_with(2020)
        expect_equal(reduce.call_args.kwargs["scale"], 100)
        expect_equal(reduce.call_args.kwargs["reducer"], earth.Reducer.sum.return_value)
        assert_geodataframe_equal(reduce.call_args.args[0], gdf)
    assert_frame_equal(frame, original.reindex(gdf.index).to_frame("urbanized_area_m2"))
    result = definitions.create_plugin().normalize_result(
        "urbanized_area", frame, job_id="local-test", location=location
    )
    expect_equal(result.model_dump()["data"], [[1800.0], [None if missing else 700.0]])


@pytest.mark.parametrize("missing", [False, True])
def test_urbanization_year_matches_original(
    location: LocationInput, *, missing: bool
) -> None:
    raw = pd.DataFrame(
        {
            "orig_index": ["zone-a2", "zone-z9"],
            "urbanization_year": [None if missing else 2020, 1985],
        }
    )
    gdf = convert_geojson_to_gdf(location)
    with (
        patch.object(year_workflow, "ee") as earth,
        patch.object(year_workflow, "_built_surface_by_year") as load,
        patch.object(year_workflow, "convert_gdf_to_ee") as convert,
    ):
        earth.data.computeFeatures.return_value = raw
        original = year_workflow.calculate_urbanization_year_table(gdf)
        frame = definitions.urbanization_year(location)
        assert_geodataframe_equal(
            convert.call_args.args[0],
            gdf[["geometry"]].to_crs("EPSG:4326").reset_index(names="orig_index"),
        )
        expect_equal(load.return_value.reduceRegions.call_args.kwargs["scale"], 100)
    expected = original.reindex(gdf.index).to_frame("urbanization_year")
    assert_frame_equal(frame.astype(float), expected.astype(float))
    expect_equal(frame.iloc[0, 0], 1985)
    expect_equal(type(frame.iloc[0, 0]), int)
    if missing:
        expect_equal(frame.iloc[1, 0], None)
    result = definitions.create_plugin().normalize_result(
        "urbanization_year", frame, job_id="local-test", location=location
    )
    expect_equal(result.model_dump()["data"], [[1985], [None if missing else 2020]])


@pytest.mark.parametrize(
    ("name", "values"),
    [
        ("temperature", {}),
        ("temperature", {"year": 2021, "season": "summer"}),
        ("temperature", {"year": 2024, "season": "rainy"}),
        ("temperature", {"year": 2024, "season": "summer", "extra": 1}),
        ("tree_coverage", {}),
        ("tree_coverage", {"min_tree_height": None}),
        ("tree_coverage", {"min_tree_height": 2.5}),
        ("tree_coverage", {"min_tree_height": 3, "extra": 1}),
        ("urbanized_area", {}),
        ("urbanized_area", {"year": 2021}),
        ("urbanized_area", {"year": 2020, "extra": 1}),
    ],
)
def test_invalid_parameters(name: str, values: dict[str, object]) -> None:
    with pytest.raises(MetricInputError):
        definitions.create_plugin().prepare_parameters(name, values)


@pytest.mark.parametrize(
    "ids",
    [
        ["zone-z9"],
        ["zone-z9", "unknown"],
        ["zone-z9", "zone-z9"],
        ["zone-z9", "zone-a2", "extra"],
        [0, 1],
    ],
)
def test_reject_unmatched_ids(location: LocationInput, ids: list[str | int]) -> None:
    parameters = definitions.TreeCoverageParameters(min_tree_height=3)
    with (
        patch.object(
            definitions,
            "calculate_tree_coverage_table",
            return_value=pd.Series(range(len(ids)), index=ids),
        ),
        pytest.raises(MetricResultError, match="each location ID exactly once"),
    ):
        definitions.tree_coverage(location, parameters)


@pytest.mark.parametrize("value", [1985.5, 2030, float("inf"), True])
def test_reject_invalid_years(location: LocationInput, *, value: float | bool) -> None:
    with (
        patch.object(
            definitions,
            "calculate_urbanization_year_table",
            return_value=pd.Series(
                [value, 2020], index=["zone-z9", "zone-a2"], dtype=object
            ),
        ),
        pytest.raises(MetricResultError, match="GHSL epoch or null"),
    ):
        definitions.urbanization_year(location)


@pytest.mark.parametrize("kind", ["columns", "order", "infinity"])
def test_normalization_rejects_invalid_output(
    location: LocationInput, kind: str
) -> None:
    frame = pd.DataFrame({"temperature_c": [10.0, 20.0]}, index=["zone-z9", "zone-a2"])
    if kind == "columns":
        frame.columns = ["wrong"]
    elif kind == "order":
        frame = frame.iloc[::-1]
    else:
        frame.iloc[0, 0] = float("inf")
    with pytest.raises(MetricResultError):
        definitions.create_plugin().normalize_result(
            "temperature", frame, job_id="local-test", location=location
        )


def test_calculation_errors_propagate(location: LocationInput) -> None:
    parameters = definitions.TemperatureParameters(year=2024, season="spring")
    with (
        patch.object(
            definitions,
            "calculate_temperature_table",
            side_effect=ValueError("No measurements"),
        ),
        pytest.raises(ValueError, match="No measurements"),
    ):
        definitions.temperature(location, parameters)


def test_import_and_factory_without_earth_engine() -> None:
    forbidden = MagicMock(side_effect=AssertionError("Import constructed EE objects"))
    with (
        patch("ee.Image", forbidden),
        patch("ee.ImageCollection", forbidden),
        patch("ee.Reducer", forbidden),
        patch("ee.Geometry", forbidden),
    ):
        for module in (
            temperature_common,
            tree_common,
            urbanization_common,
            temperature_workflow,
            tree_workflow,
            area_workflow,
            year_workflow,
            definitions,
        ):
            importlib.reload(module)
        plugin = definitions.create_plugin()
    expect_equal(
        set(plugin.metric_names),
        {"temperature", "tree_coverage", "urbanized_area", "urbanization_year"},
    )
