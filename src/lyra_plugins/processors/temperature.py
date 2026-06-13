import functools
from typing import Literal

import ee
from lyra.sdk.types import ExplicitLocationAPI
from lyra.utils.date import get_season_date_range
from lyra.utils.ee import reduce_ee_image_over_gdf_factory

from lyra_plugins.functions.temperature import reduce_landsat_collection
from lyra_plugins.models.temperature import AllowedLandsatYears

METRIC_DESCRIPTION = (
    "Average surface temperature in degrees Celsius, derived from Landsat 9 "
    "thermal band (Band 10)."
)

TAVI_HINT = (
    "Use this tool when the user asks about heat, temperature, urban "
    "heat islands, or thermal conditions. Returns the average daytime land "
    "surface temperature (degrees Celsius) for each census tract, derived from "
    "satellite imagery."
)


def calculate(
    data: ExplicitLocationAPI,
    year: AllowedLandsatYears,
    season: Literal["spring", "summer", "autumn", "winter"],
) -> dict:
    start_date, end_date = get_season_date_range(season, year)

    load_img_func = functools.partial(
        reduce_landsat_collection,
        start_date=start_date,
        end_date=end_date,
        col_idx=8 if year < 2022 else 9,
    )
    return reduce_ee_image_over_gdf_factory(
        load_img_func,
        reducer=ee.Reducer.mean(),
        scale=30,
    )(data)
