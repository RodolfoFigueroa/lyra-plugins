import geopandas as gpd
import pandarm as pdna
import pandas as pd
from lyra.sdk.db_types import Bounds
from pyproj import CRS, Transformer


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


def _project_bounds_to_latlon(
    bounds: Bounds,
    bounds_crs: str | CRS,
) -> Bounds:
    """Reproject a bounding box to WGS 84 (EPSG:4326) longitude/latitude.

    If the provided CRS is already WGS 84, the bounds are returned unchanged.

    Args:
        xmin: Minimum x coordinate of the bounding box.
        ymin: Minimum y coordinate of the bounding box.
        xmax: Maximum x coordinate of the bounding box.
        ymax: Maximum y coordinate of the bounding box.
        bounds_crs: CRS of the input coordinates, as an EPSG string or
            ``pyproj.CRS`` object.

    Returns:
        A tuple ``(xmin, ymin, xmax, ymax)`` reprojected to WGS 84
        (longitude/latitude).
    """
    crs = CRS.from_user_input(bounds_crs)
    latlon_crs = CRS.from_epsg(4326)

    if crs != latlon_crs:
        transformer = Transformer.from_crs(crs, latlon_crs, always_xy=True)
        xmin, ymin = transformer.transform(bounds.xmin, bounds.ymin)
        xmax, ymax = transformer.transform(bounds.xmax, bounds.ymax)

    return Bounds(xmin, ymin, xmax, ymax)
