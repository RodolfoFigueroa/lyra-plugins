import os
import tempfile

import ee
import geemap
import geopandas as gpd
import pandarm as pdna
import pandas as pd
import rasterio as rio


def get_geometries_osmid(
    geometries: gpd.GeoDataFrame,
    net_accessibility: pdna.Network,
    *,
    mapping_distance: float = 1000,
) -> pd.Series:
    return net_accessibility.get_node_ids(
        x_col=geometries["geometry"].centroid.x,
        y_col=geometries["geometry"].centroid.y,
        # Despite what pandana documentation says, this mapping distance is
        # just standard Euclidean, not based on network impedance. Thus, we
        # don't need to scale it.
        mapping_distance=mapping_distance,
    )


def download_ee_image(
    img: ee.Image,
    bounds: ee.Geometry,
    fpath: os.PathLike,
    download_kwargs: dict,
) -> None:
    with tempfile.NamedTemporaryFile(suffix=".tif") as tmp:
        geemap.download_ee_image(img, tmp.name, region=bounds, **download_kwargs)

        with rio.open(tmp.name) as src:
            profile = src.profile
            profile.update(
                count=1,
                compress="lzw",
            )

            with rio.open(fpath, "w", **profile) as dst:
                dst.write(src.read(1), 1)
