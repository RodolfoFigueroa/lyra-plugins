import ee
import geopandas as gpd
import pandas as pd
from lyra.utils.ee import reduce_ee_image_over_gdf

from lyra_plugins.metrics.tree_coverage.common import load_tree_coverage_area_img

TREE_COVERAGE_COLUMN = "tree_coverage_m2"
ANALYSIS_SCALE_M = 1


def calculate_tree_coverage_table(
    gdf: gpd.GeoDataFrame, min_tree_height: int
) -> pd.Series:
    gdf = gdf.to_crs("EPSG:4326")
    bbox = ee.Geometry.BBox(*gdf.total_bounds)
    img = load_tree_coverage_area_img(bbox, min_tree_height=min_tree_height)
    return reduce_ee_image_over_gdf(
        gdf, img, reducer=ee.Reducer.sum(), scale=ANALYSIS_SCALE_M
    )
