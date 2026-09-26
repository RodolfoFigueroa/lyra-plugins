from typing import Literal

import pandas as pd
from lyra.sdk import (
    LocationInput,
    MetricParameters,
    MetricResultError,
    PluginDefinition,
    TableColumn,
    TableOutput,
    Unit,
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
        description=(
            "Calendar year from 2022 through 2025. Winter starts in December "
            "of the preceding year and ends in February of this year."
        )
    )
    season: Literal["spring", "summer", "autumn", "winter"] = Field(
        description=(
            "Meteorological season: spring March-May, summer June-August, "
            "autumn September-November, winter December-February. The selected "
            "period includes the first day and excludes the last calendar day "
            "of the season."
        )
    )


class TreeCoverageParameters(MetricParameters):
    min_tree_height: int = Field(
        description=(
            "Minimum estimated canopy height in metres. Pixels equal to "
            "or above this threshold contribute their area; lower pixels do not."
        )
    )


class UrbanizedAreaParameters(MetricParameters):
    year: AllowedGhslYearsT = Field(
        description=(
            "GHSL P2023A calendar-year epoch from 1975 through 2025 in five-year "
            "increments, selecting the built-up surface estimate for that epoch."
        )
    )


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
    description=(
        "Compute seasonal mean land-surface temperature in Celsius per polygon. "
        "Use Landsat 9 Collection 2 Tier 1 Level 2 (LANDSAT/LC09/C02/T1_L2), "
        "mask dilated clouds, clouds, and cloud shadows, average images over "
        "the selected season, then take a spatial mean at 30 m reduction "
        "resolution. This estimates surface temperature rather than air "
        "temperature. Cloud masking and missing source temperature data limit "
        "usable observations."
    ),
    output=TableOutput(
        columns=[
            TableColumn(
                name="temperature_c",
                type="number",
                unit=Unit.DEGREE_CELSIUS,
                description=(
                    "Spatial mean of seasonal mean land-surface temperature in "
                    "degrees Celsius. Null denotes an unavailable polygon "
                    "reduction, including a polygon without usable temperature "
                    "pixels."
                ),
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
    description=(
        "Sum the area meeting a minimum estimated canopy height per polygon. "
        "Use the Meta/WRI canopy-height collection "
        "projects/sat-io/open-datasets/facebook/meta-canopy-height, taking the "
        "pixelwise maximum across intersecting images and summing qualifying "
        "pixel areas at 1 m reduction resolution. The source imagery spans "
        "2009-2020, predominantly 2018-2020, so the result represents a canopy "
        "baseline assembled from imagery of different dates. "
        "Source: https://gee-community-catalog.org/projects/meta_trees/"
    ),
    output=TableOutput(
        columns=[
            TableColumn(
                name="tree_coverage_m2",
                type="number",
                unit=Unit.SQUARE_METRE,
                description=(
                    "Sum of pixel area with estimated canopy height at least "
                    "min_tree_height, in square metres. Zero can reflect "
                    "below-threshold or masked source pixels and does not "
                    "establish an observed absence of trees. Null means the "
                    "polygon reduction returned no value."
                ),
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
    description=(
        "Sum estimated built-up surface area per polygon for a GHSL epoch. "
        "Use JRC/GHSL/P2023A/GHS_BUILT_S and a spatial sum at 100 m reduction "
        "resolution. GHSL epochs include spatial and temporal interpolation "
        "or extrapolation."
    ),
    output=TableOutput(
        columns=[
            TableColumn(
                name="urbanized_area_m2",
                type="number",
                unit=Unit.SQUARE_METRE,
                description=(
                    "Total estimated built-up surface in square metres for the "
                    "selected epoch. Zero is a computed zero total; null denotes "
                    "an unavailable polygon reduction."
                ),
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
        "Estimate the first GHSL epoch when built-up surface reaches at least "
        "20% of each polygon's area. Sum estimated built-up surface from "
        "JRC/GHSL/P2023A/GHS_BUILT_S at 100 m reduction resolution for each "
        "five-year epoch from 1975 through 2025.\n\n"
        "The result is the earliest qualifying calendar-year epoch, not an "
        "exact development date or elapsed duration. A result of 1975 may "
        "reflect development before the first supported epoch. GHSL includes "
        "spatial and temporal interpolation or extrapolation."
    ),
    output=TableOutput(
        columns=[
            TableColumn(
                name="urbanization_year",
                type="integer",
                unit=Unit.CALENDAR_YEAR,
                description=(
                    "Earliest five-year GHSL epoch from 1975 through 2025 meeting "
                    "the 20% built-up-area threshold. Null means no epoch "
                    "qualified; it is not a zero year or proof that the polygon "
                    "was never developed."
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
