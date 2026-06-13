import tempfile
from pathlib import Path
from typing import Literal
from uuid import uuid4

import geemap
import rasterio as rio
from lyra.sdk.types import ExplicitBoundsAPI
from lyra.utils.date import get_season_date_range
from lyra.utils.ee import convert_polygon_to_ee
from lyra.utils.geometry import convert_geojson_to_gdf

from lyra_plugins.functions.temperature import reduce_landsat_collection
from lyra_plugins.models.temperature import AllowedLandsatYears

METRIC_DESCRIPTION: str = (
    "Surface temperature raster in degrees Celsius, derived from Landsat 9 "
    "thermal band (Band 10)."
)
RETURNS_FILE = True


def calculate(
    data: ExplicitBoundsAPI,
    year: AllowedLandsatYears,
    season: Literal["spring", "summer", "autumn", "winter"],
) -> str:
    gdf = convert_geojson_to_gdf(data).to_crs("EPSG:4326")
    bounds = convert_polygon_to_ee(gdf["geometry"].iloc[0])

    start_date, end_date = get_season_date_range(season, year)
    img = reduce_landsat_collection(
        bounds, start_date, end_date, col_idx=8 if year < 2022 else 9
    )

    fpath = Path("/lyra_cache") / f"{uuid4().hex}.tif"

    with tempfile.NamedTemporaryFile(suffix=".tif") as tmp:
        geemap.download_ee_image(
            img,
            tmp.name,
            region=bounds,
            dtype="float32",
            crs="EPSG:4326",
            scale=30,
            resampling="near",
        )

        with rio.open(tmp.name) as src:
            profile = src.profile
            profile.update(
                count=1,
                compress="lzw",
            )

            with rio.open(fpath, "w", **profile) as dst:
                dst.write(src.read(1), 1)

    return str(fpath)
