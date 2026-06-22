from pathlib import Path
from uuid import uuid4

from lyra.sdk.types import ExplicitBoundsAPI
from lyra.utils.ee import convert_polygon_to_ee
from lyra.utils.geometry import convert_geojson_to_gdf

from lyra_plugins.functions.base import download_ee_image
from lyra_plugins.functions.tree_coverage import load_tree_coverage_img

METRIC_DESCRIPTION: str = (
    "Tree canopy coverage fraction raster, derived from high-resolution aerial imagery."
)
RETURNS_FILE = True


def calculate(data: ExplicitBoundsAPI, crs: str = "EPSG:4326", scale: int = 10) -> str:
    gdf = convert_geojson_to_gdf(data).to_crs("EPSG:4326")
    bounds = convert_polygon_to_ee(gdf["geometry"].iloc[0])

    img = load_tree_coverage_img(bounds)

    fpath = Path("/lyra_cache") / f"{uuid4().hex}.tif"
    download_ee_image(
        img,
        bounds,
        fpath,
        download_kwargs={
            "dtype": "float32",
            "crs": crs,
            "scale": scale,
            "resampling": "near",
        },
    )
    return str(fpath)
