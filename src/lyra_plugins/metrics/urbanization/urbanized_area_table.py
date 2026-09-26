import ee
import geopandas as gpd
import pandas as pd
from lyra.utils.ee import reduce_ee_image_over_gdf

from lyra_plugins.metrics.urbanization.common import (
    GHSL_ANALYSIS_SCALE_M,
    AllowedGhslYearsT,
    load_urbanized_area_img,
)


def calculate_urbanized_area_table(
    gdf: gpd.GeoDataFrame, year: AllowedGhslYearsT
) -> pd.Series:
    return reduce_ee_image_over_gdf(
        gdf,
        load_urbanized_area_img(year),
        reducer=ee.Reducer.sum(),
        scale=GHSL_ANALYSIS_SCALE_M,
    )
