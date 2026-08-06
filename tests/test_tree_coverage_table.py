import inspect
from collections.abc import Callable
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Self, cast

import ee
import numpy as np
import pytest
from lyra.sdk.models.geometry import (
    CRS,
    CRSProperties,
    Feature,
    GeoJSON,
    PolygonGeometry,
)

from lyra_plugins.definitions import create_plugin
from lyra_plugins.metrics.tree_coverage import common, raster, table

if TYPE_CHECKING:
    from lyra.sdk.context import RunContext


def _location() -> GeoJSON:
    return GeoJSON(
        type="FeatureCollection",
        features=[
            Feature(
                id="polygon-a",
                type="Feature",
                geometry=PolygonGeometry(
                    type="Polygon",
                    coordinates=[
                        [[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]],
                    ],
                ),
                properties={},
            ),
            Feature(
                id="polygon-b",
                type="Feature",
                geometry=PolygonGeometry(
                    type="Polygon",
                    coordinates=[
                        [[2, 2], [2, 3], [3, 3], [3, 2], [2, 2]],
                    ],
                ),
                properties={},
            ),
        ],
        crs=CRS(type="name", properties=CRSProperties(name="EPSG:4326")),
    )


def test_run_returns_native_scale_coverage_in_input_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, Any] = {}
    bounds = object()
    area_image = object()
    reducer = cast("ee.Reducer", object())

    def load_area_image(received_bounds: object, min_tree_height: int) -> object:
        calls["load"] = (received_bounds, min_tree_height)
        return area_image

    def factory(
        load_img_func: Callable[[object], object],
        *,
        reducer: ee.Reducer,
        scale: int,
    ) -> Callable[[object], dict[str, float]]:
        calls["image"] = load_img_func(bounds)
        calls["reducer"] = reducer
        calls["scale"] = scale
        return lambda _location: {"polygon-b": 12.5, "polygon-a": float("nan")}

    monkeypatch.setattr(table, "load_tree_coverage_area_img", load_area_image)
    monkeypatch.setattr(table, "reduce_ee_image_over_gdf_factory", factory)
    monkeypatch.setattr(table.ee.Reducer, "sum", lambda: reducer)

    result = table.run(
        _location(),
        min_tree_height=3,
        context=cast("RunContext", SimpleNamespace(job_id="job-1")),
    )

    np.testing.assert_equal(calls["load"], (bounds, 3))
    np.testing.assert_equal(calls["image"], area_image)
    np.testing.assert_equal(calls["reducer"], reducer)
    np.testing.assert_equal(calls["scale"], 1)
    np.testing.assert_equal(result.job_id, "job-1")
    np.testing.assert_equal(result.index, ["polygon-a", "polygon-b"])
    np.testing.assert_equal(result.columns, ["tree_coverage_m2"])
    np.testing.assert_equal(result.data, [[0.0], [12.5]])


class _FakeImage:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def gte(self, value: object) -> Self:
        self.calls.append(("gte", value))
        return self

    def unmask(self, value: object, *, sameFootprint: bool) -> Self:  # noqa: N803
        self.calls.append(("unmask", (value, sameFootprint)))
        return self

    def multiply(self, value: object) -> Self:
        self.calls.append(("multiply", value))
        return self

    def rename(self, value: object) -> Self:
        self.calls.append(("rename", value))
        return self

    def clip(self, value: object) -> Self:
        self.calls.append(("clip", value))
        return self


def test_load_tree_coverage_area_img_builds_square_metre_image(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bounds = cast("ee.Geometry", object())
    image = _FakeImage()
    pixel_area = object()
    monkeypatch.setattr(common, "load_tree_coverage_img", lambda _bounds: image)
    monkeypatch.setattr(common.ee, "Number", lambda value: ("number", value))
    monkeypatch.setattr(common.ee.Image, "pixelArea", lambda: pixel_area)

    result = common.load_tree_coverage_area_img(bounds, min_tree_height=4)

    np.testing.assert_equal(result, image)
    np.testing.assert_equal(
        image.calls,
        [
            ("gte", ("number", 4)),
            ("unmask", (0, False)),
            ("multiply", pixel_area),
            ("rename", "tree_coverage_m2"),
            ("clip", bounds),
        ],
    )


def test_tree_coverage_metric_is_registered_with_table_schema() -> None:
    plugin = create_plugin()
    description = plugin.describe("tree_coverage")

    np.testing.assert_equal(
        plugin.metric_names,
        ("accessibility_jobs", "tree_coverage"),
    )
    np.testing.assert_equal(description.inputs["location"].kind, "location")
    np.testing.assert_equal(
        description.inputs["min_tree_height"].model_dump()["minimum"],
        0,
    )
    np.testing.assert_equal(
        description.inputs["min_tree_height"].model_dump()["default"],
        3,
    )
    np.testing.assert_equal(
        actual=description.inputs["min_tree_height"].model_dump()["required"],
        desired=False,
    )
    np.testing.assert_equal(
        description.output.model_dump(),
        {
            "kind": "table",
            "columns": [
                {
                    "name": "tree_coverage_m2",
                    "type": "number",
                    "unit": "m2",
                    "description": (
                        "Area in square metres covered by trees meeting the minimum "
                        "height threshold."
                    ),
                    "nullable": False,
                },
            ],
            "batched_columns": [],
        },
    )


def test_tree_coverage_metrics_default_to_three_metre_height() -> None:
    np.testing.assert_equal(
        inspect.signature(raster.run).parameters["min_tree_height"].default,
        3,
    )
    np.testing.assert_equal(
        inspect.signature(table.run).parameters["min_tree_height"].default,
        3,
    )
