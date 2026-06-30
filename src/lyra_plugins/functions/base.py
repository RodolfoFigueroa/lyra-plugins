import os
import tempfile

import ee
import geopandas as gpd
import pandarm as pdna
import pandas as pd
import rasterio as rio
from geedim.image import ImageAccessor

_GEEDIM_TO_GEOTIFF_KWARGS = frozenset(
    {
        "driver",
        "max_cpus",
        "max_requests",
        "max_tile_bands",
        "max_tile_dim",
        "max_tile_size",
        "nodata",
    }
)


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
    export_kwargs = dict(download_kwargs)
    if bounds is not None:
        export_kwargs["region"] = bounds

    export_kwargs.pop("num_threads", None)
    unmask_value = export_kwargs.pop("unmask_value", None)
    if unmask_value is not None:
        if isinstance(bounds, ee.Geometry):
            img = img.clip(bounds)
        elif isinstance(bounds, ee.FeatureCollection):
            img = img.clipToCollection(bounds)
        img = img.unmask(unmask_value, sameFootprint=False)

    to_geotiff_kwargs = {"overwrite": export_kwargs.pop("overwrite", True)}
    for key in _GEEDIM_TO_GEOTIFF_KWARGS:
        if key in export_kwargs:
            to_geotiff_kwargs[key] = export_kwargs.pop(key)

    with tempfile.NamedTemporaryFile(suffix=".tif") as tmp:
        prepared_img = ImageAccessor(img).prepareForExport(**export_kwargs)
        ImageAccessor(prepared_img).toGeoTIFF(tmp.name, **to_geotiff_kwargs)

        with rio.open(tmp.name) as src:
            profile = src.profile
            profile.update(
                count=1,
                compress="lzw",
            )

            with rio.open(fpath, "w", **profile) as dst:
                dst.write(src.read(1), 1)
