from typing import Literal

import ee
import geopandas as gpd
import pandas as pd
from lyra.utils.date import get_season_date_range
from lyra.utils.ee import reduce_ee_image_over_gdf

from lyra_plugins.metrics.temperature.common import load_temperature_img

ANALYSIS_SCALE_M = 30


def calculate_temperature_table(
    gdf: gpd.GeoDataFrame,
    year: Literal[2022, 2023, 2024, 2025],
    season: Literal["spring", "summer", "autumn", "winter"],
) -> pd.Series:
    gdf = gdf.to_crs("EPSG:4326")
    bbox = ee.Geometry.BBox(*gdf.total_bounds)

    start_date, end_date = get_season_date_range(season=season, year=year)

    img = load_temperature_img(bbox, start_date, end_date, col_idx=9)
    return reduce_ee_image_over_gdf(
        gdf, img, reducer=ee.Reducer.mean(), scale=ANALYSIS_SCALE_M
    )
