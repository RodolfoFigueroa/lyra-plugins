import ee
import geopandas as gpd
import pandas as pd
from lyra.utils.ee import convert_gdf_to_ee

from lyra_plugins.metrics.urbanization.common import (
    AVAILABLE_GHSL_YEARS,
    GHSL_ANALYSIS_SCALE_M,
    GHSL_BUILT_SURFACE_BAND,
    load_urbanized_area_img,
)

URBANIZATION_YEAR_COLUMN = "urbanization_year"
URBANIZED_AREA_FRACTION = 0.2


def _built_surface_by_year(bbox: ee.Geometry) -> ee.Image:
    images = [
        load_urbanized_area_img(year).rename(f"{GHSL_BUILT_SURFACE_BAND}_{year}")
        for year in AVAILABLE_GHSL_YEARS
    ]
    return ee.Image.cat(images).clip(bbox)


def _set_urbanization_year(feature: ee.Feature) -> ee.Feature:
    feature = ee.Feature(feature)
    urbanized_area_threshold = (
        feature.geometry().area(maxError=1).multiply(URBANIZED_AREA_FRACTION)
    )

    earliest_year = ee.Number(-1)
    for year in reversed(AVAILABLE_GHSL_YEARS):
        built_surface = ee.Number(feature.get(f"{GHSL_BUILT_SURFACE_BAND}_{year}"))
        earliest_year = ee.Number(
            ee.Algorithms.If(
                built_surface.gte(urbanized_area_threshold),
                year,
                earliest_year,
            )
        )

    return ee.Feature(
        feature.set(
            URBANIZATION_YEAR_COLUMN,
            ee.Algorithms.If(earliest_year.eq(-1), None, earliest_year),
        )
    )


def calculate_urbanization_year_table(gdf: gpd.GeoDataFrame) -> pd.Series:
    """Return the first GHSL epoch at least 20% of each polygon was urbanized."""
    gdf = gdf[["geometry"]].to_crs("EPSG:4326")
    bbox = ee.Geometry.BBox(*gdf.total_bounds)
    image = _built_surface_by_year(bbox)
    features = convert_gdf_to_ee(gdf.reset_index(names="orig_index"))
    reduced = image.reduceRegions(
        collection=features,
        reducer=ee.Reducer.sum(),
        scale=GHSL_ANALYSIS_SCALE_M,
    ).map(_set_urbanization_year)
    computed = ee.data.computeFeatures(
        {
            "expression": reduced.select(
                ["orig_index", URBANIZATION_YEAR_COLUMN],
            ),
            "fileFormat": "PANDAS_DATAFRAME",
        }
    )
    return computed.set_index("orig_index")[URBANIZATION_YEAR_COLUMN]
