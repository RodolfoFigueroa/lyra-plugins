from typing import Literal

import pandas as pd
from lyra.sdk import (
    LocationInput,
    MetricParameters,
    MetricResultError,
    PluginDefinition,
    TableColumn,
    TableOutput,
    metric,
)
from lyra.utils.geometry import convert_geojson_to_gdf
from pydantic import Field

from lyra_plugins.metrics.temperature.table import calculate_temperature_table
from lyra_plugins.metrics.tree_coverage.table import calculate_tree_coverage_table
from lyra_plugins.metrics.urbanization.common import (
    AVAILABLE_GHSL_YEARS,
    AllowedGhslYearsT,
)
from lyra_plugins.metrics.urbanization.urbanization_year_table import (
    calculate_urbanization_year_table,
)
from lyra_plugins.metrics.urbanization.urbanized_area_table import (
    calculate_urbanized_area_table,
)


class TemperatureParameters(MetricParameters):
    year: Literal[2022, 2023, 2024, 2025] = Field(
        description="Season year; winter starts in December of the preceding year."
    )
    season: Literal["spring", "summer", "autumn", "winter"] = Field(
        description=(
            "Meteorological season: spring March-May, summer June-August, "
            "autumn September-November, winter December-February."
        )
    )


class TreeCoverageParameters(MetricParameters):
    min_tree_height: int = Field(
        description="Minimum canopy height in metres, included in the coverage area."
    )


class UrbanizedAreaParameters(MetricParameters):
    year: AllowedGhslYearsT = Field(description="GHSL built-up surface epoch.")


def _as_table(
    values: pd.Series,
    index: pd.Index,
    column: str,
    metric_name: str,
) -> pd.DataFrame:
    if (
        not values.index.is_unique
        or len(values) != len(index)
        or not values.index.isin(index).all()
    ):
        raise MetricResultError(
            metric_name,
            "index",
            "Calculation must return each location ID exactly once.",
        )
    # Reorder by the original feature IDs, never by the returned row positions.
    return values.reindex(index).to_frame(name=column)


@metric(
    name="temperature",
    description="Seasonal mean Landsat 9 land-surface temperature at 30 m resolution.",
    output=TableOutput(
        columns=[
            TableColumn(
                name="temperature_c",
                type="number",
                unit="degC",
                description="Mean land-surface temperature after cloud masking.",
                nullable=True,
            )
        ]
    ),
)
def temperature(
    location: LocationInput, parameters: TemperatureParameters
) -> pd.DataFrame:
    gdf = convert_geojson_to_gdf(location)
    values = calculate_temperature_table(gdf, parameters.year, parameters.season)
    return _as_table(values, gdf.index, "temperature_c", "temperature")


@metric(
    name="tree_coverage",
    description="Area meeting the minimum canopy height, reduced at 1 m resolution.",
    output=TableOutput(
        columns=[
            TableColumn(
                name="tree_coverage_m2",
                type="number",
                unit="m2",
                description="Area with canopy height at least min_tree_height.",
                nullable=True,
            )
        ]
    ),
)
def tree_coverage(
    location: LocationInput, parameters: TreeCoverageParameters
) -> pd.DataFrame:
    gdf = convert_geojson_to_gdf(location)
    values = calculate_tree_coverage_table(gdf, parameters.min_tree_height)
    return _as_table(values, gdf.index, "tree_coverage_m2", "tree_coverage")


@metric(
    name="urbanized_area",
    description="GHSL built-up surface summed for an epoch at 100 m resolution.",
    output=TableOutput(
        columns=[
            TableColumn(
                name="urbanized_area_m2",
                type="number",
                unit="m2",
                description="Total built-up surface in the selected GHSL epoch.",
                nullable=True,
            )
        ]
    ),
)
def urbanized_area(
    location: LocationInput, parameters: UrbanizedAreaParameters
) -> pd.DataFrame:
    gdf = convert_geojson_to_gdf(location)
    values = calculate_urbanized_area_table(gdf, parameters.year)
    return _as_table(values, gdf.index, "urbanized_area_m2", "urbanized_area")


@metric(
    name="urbanization_year",
    description=(
        "First GHSL epoch from 1975 through 2025 when built-up surface reaches "
        "20% of the polygon area, reduced at 100 m resolution."
    ),
    output=TableOutput(
        columns=[
            TableColumn(
                name="urbanization_year",
                type="integer",
                unit="year",
                description=(
                    "First qualifying GHSL calendar year; null if no epoch qualifies."
                ),
                nullable=True,
            )
        ]
    ),
)
def urbanization_year(location: LocationInput) -> pd.DataFrame:
    gdf = convert_geojson_to_gdf(location)
    frame = _as_table(
        calculate_urbanization_year_table(gdf),
        gdf.index,
        "urbanization_year",
        "urbanization_year",
    )
    # Pandas represents integer years with missing values as floats. Preserve
    # missing years and convert only exact, supported epochs to native integers.
    years: list[int | None] = []
    for value in frame["urbanization_year"]:
        if pd.isna(value):
            years.append(None)
        elif not isinstance(value, bool) and value in AVAILABLE_GHSL_YEARS:
            years.append(int(value))
        else:
            name = "urbanization_year"
            raise MetricResultError(name, name, "Expected a GHSL epoch or null.")
    frame["urbanization_year"] = pd.Series(years, index=gdf.index, dtype=object)
    return frame


def create_plugin() -> PluginDefinition:
    return PluginDefinition(
        metrics=[temperature, tree_coverage, urbanized_area, urbanization_year]
    )
