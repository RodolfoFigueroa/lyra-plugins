from typing import Literal

import geopandas as gpd
import networkx as nx
import osmnx as ox
import pandarm as pdna
from lyra.sdk.db_types import Bounds
from pyproj import CRS

from lyra_plugins.constants import WALK_SPEED_KPH
from lyra_plugins.functions.base import _project_bounds_to_latlon


def load_roads_from_bounds(
    bounds: Bounds,
    *,
    bounds_crs: str | CRS,
    network_type: Literal["drive", "walk"],
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Load a road network from OSM for a given bounding box.

    Fetches the road graph via OSMnx, computes edge speeds and travel times,
    and returns nodes and edges as separate GeoDataFrames. Node geometries are
    reprojected to ``bounds_crs``; walk networks use a fixed speed of
    ``WALK_SPEED_KPH``.

    Args:
        xmin: Minimum x coordinate of the bounding box.
        ymin: Minimum y coordinate of the bounding box.
        xmax: Maximum x coordinate of the bounding box.
        ymax: Maximum y coordinate of the bounding box.
        bounds_crs: CRS of the input coordinates.
        network_type: Either ``"drive"`` or ``"walk"``.

    Returns:
        A tuple ``(nodes, edges)`` where:
        - ``nodes`` is a GeoDataFrame of node geometries in ``bounds_crs``.
        - ``edges`` is a DataFrame with columns
          ``["u", "v", "length", "travel_time"]``.
    """
    bounds = _project_bounds_to_latlon(
        bounds,
        bounds_crs,
    )

    g = ox.graph_from_bbox(bbox=tuple(bounds), network_type=network_type)

    if network_type == "drive":
        g = ox.add_edge_speeds(g)
    else:
        nx.set_edge_attributes(g, name="speed_kph", values=WALK_SPEED_KPH)
    g = ox.add_edge_travel_times(g)
    nodes, edges = ox.graph_to_gdfs(g)

    nodes = nodes.to_crs(bounds_crs).filter(["geometry"])
    edges = edges.reset_index()[["u", "v", "length", "travel_time"]]

    return nodes, edges


def load_accessibility_net_from_bounds(
    bounds: Bounds,
    *,
    bounds_crs: str | CRS,
    network_type: Literal["drive", "walk"],
) -> pdna.Network:
    """Build a Pandana accessibility network from OSM roads within a bounding box.

    Loads the road graph via :func:`load_roads_from_bounds` and constructs a
    ``pandana.Network`` ready for accessibility analysis.

    Args:
        xmin: Minimum x coordinate of the bounding box.
        ymin: Minimum y coordinate of the bounding box.
        xmax: Maximum x coordinate of the bounding box.
        ymax: Maximum y coordinate of the bounding box.
        bounds_crs: CRS of the input coordinates.
        network_type: Either ``"drive"`` or ``"walk"``.

    Returns:
        A ``pandana.Network`` built from the OSM road graph, with ``length``
        and ``travel_time`` as edge impedances.
    """
    nodes, edges = load_roads_from_bounds(
        bounds,
        bounds_crs=bounds_crs,
        network_type=network_type,
    )
    return pdna.Network(
        nodes["geometry"].x.copy(),
        nodes["geometry"].y.copy(),
        edges["u"].copy(),
        edges["v"].copy(),
        edges[["length", "travel_time"]].copy(),
    )
