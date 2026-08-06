import math
from collections.abc import Mapping
from functools import partial

import ee
from lyra.sdk import Input, LocationInput, TableJobResult, metric
from lyra.sdk.context import RunContext
from lyra.sdk.models.plugin_v4 import TableOutputColumnV4, TableOutputV4
from lyra.utils.ee import reduce_ee_image_over_gdf_factory

from lyra_plugins.metrics.tree_coverage.common import load_tree_coverage_area_img

TREE_COVERAGE_COLUMN = "tree_coverage_m2"
ANALYSIS_SCALE_M = 1


def _normalize_coverage_values(
    values: Mapping[str, float | None],
) -> dict[str, float]:
    return {
        feature_id: 0.0 if value is None or math.isnan(value) else float(value)
        for feature_id, value in values.items()
    }


@metric(
    name="tree_coverage",
    description=(
        "Computes the area covered by trees meeting the requested minimum height "
        "for each input polygon, using the Meta canopy-height Earth Engine image."
    ),
    inputs={
        "min_tree_height": Input(
            description="Minimum canopy height in metres counted as tree coverage.",
            ge=0,
        ),
    },
    output=TableOutputV4(
        kind="table",
        columns=[
            TableOutputColumnV4(
                name=TREE_COVERAGE_COLUMN,
                type="number",
                unit="m2",
                description=(
                    "Area in square metres covered by trees meeting the minimum "
                    "height threshold."
                ),
                nullable=False,
            )
        ],
    ),
)
def run(
    location: LocationInput,
    min_tree_height: int = 3,
    *,
    context: RunContext,
) -> TableJobResult:
    calculate_coverage = reduce_ee_image_over_gdf_factory(
        partial(
            load_tree_coverage_area_img,
            min_tree_height=min_tree_height,
        ),
        reducer=ee.Reducer.sum(),
        scale=ANALYSIS_SCALE_M,
    )
    coverage_by_feature = _normalize_coverage_values(calculate_coverage(location))
    feature_ids = [feature.id for feature in location.features]

    return TableJobResult.from_mapping(
        context.job_id,
        feature_ids,
        [TREE_COVERAGE_COLUMN],
        {
            TREE_COVERAGE_COLUMN: [
                coverage_by_feature[feature_id] for feature_id in feature_ids
            ]
        },
    )
