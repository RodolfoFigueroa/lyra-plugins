from typing import Literal, NamedTuple

import geopandas as gpd
import numpy as np
import pandarm as pdna
import pandas as pd
from lyra.sdk import (
    BatchInput,
    BatchItem,
    FailedJobResult,
    Input,
    LocationInput,
    LyraDB,
    TableJobResult,
    metric,
)
from lyra.sdk.context import RunContext
from lyra.sdk.db_types import Bounds
from lyra.sdk.models.plugin_v4 import (
    BatchedTableOutputColumnV4,
    TableOutputV4,
)
from lyra.utils.geometry import convert_geojson_to_gdf
from pydantic import ValidationError

from lyra_plugins.constants import PER_OCU_TO_NUM_WORKERS_MAP
from lyra_plugins.functions.base import get_geometries_osmid
from lyra_plugins.functions.osm import load_accessibility_net_from_bounds

WANTED_CRS = "EPSG:6372"


class Networks(NamedTuple):
    drive: pdna.Network
    walk: pdna.Network


def get_networks(bounds: Bounds) -> Networks:
    return Networks(
        **{
            network_type: load_accessibility_net_from_bounds(
                bounds,
                bounds_crs=WANTED_CRS,
                network_type=network_type,
            )
            for network_type in ("drive", "walk")
        }
    )


def get_denue(
    bounds: Bounds,
    db: LyraDB,
    *,
    year: Literal[2020, 2021, 2022, 2023, 2024, 2025] = 2025,
    month: Literal[5, 11] | None,
    nets: Networks,
) -> gpd.GeoDataFrame:
    if month is None:
        month = 5 if year == 2025 else 11

    return (
        db.load_denue_from_bounds(bounds, year=year, month=month)
        .to_crs(WANTED_CRS)
        .assign(num_workers=lambda x: x["per_ocu"].map(PER_OCU_TO_NUM_WORKERS_MAP))
        .drop(columns=["per_ocu"])
        .assign(
            osmid_drive=lambda df: get_geometries_osmid(df, nets.drive),  # ty: ignore[invalid-argument-type]
            osmid_walk=lambda df: get_geometries_osmid(df, nets.walk),  # ty: ignore[invalid-argument-type]
        )
    )


def get_mesh(
    bounds: Bounds,
    db: LyraDB,
    nets: Networks,
) -> gpd.GeoDataFrame:
    return db.load_mesh_from_bounds(bounds)[["geometry"]].assign(
        osmid_drive=lambda df: get_geometries_osmid(
            df,  # ty:ignore[invalid-argument-type]
            nets.drive,
        ),
        osmid_walk=lambda df: get_geometries_osmid(
            df,  # ty:ignore[invalid-argument-type]
            nets.walk,
        ),
    )


def calculate_for_items(  # noqa: PLR0913
    item_key: str,
    *,
    df: gpd.GeoDataFrame,
    denue: gpd.GeoDataFrame,
    mesh: gpd.GeoDataFrame,
    nets: Networks,
    network_type: Literal["drive", "walk"],
    pattern: str,
    max_weight: float,
    edge_weights: Literal["length", "travel_time"],
) -> pd.Series:
    if network_type == "drive":
        net_accessibility = nets.drive
        osmid_col = "osmid_drive"
    elif network_type == "walk":
        net_accessibility = nets.walk
        osmid_col = "osmid_walk"

    denue_osmid_group = (
        denue.loc[lambda df: df["codigo_act"].str.match(pattern)]
        .groupby(osmid_col)["num_workers"]
        .sum()
    )

    source_nodes = mesh[osmid_col].dropna().unique()
    nodes_in_range = net_accessibility.nodes_in_range(
        source_nodes,
        max_weight,
        imp_name=edge_weights,
    )
    workers = nodes_in_range["destination"].map(denue_osmid_group)
    routes_with_jobs = nodes_in_range.loc[workers.notna()]
    accessibility = (
        pd.Series(
            workers.loc[routes_with_jobs.index].to_numpy()
            * np.exp(-routes_with_jobs[edge_weights].to_numpy() / max_weight),
            index=routes_with_jobs["source"],
        )
        .groupby(level=0)
        .sum()
        .reindex(source_nodes, fill_value=0)
        .rename(f"jobs_{item_key}")
    )

    mesh_joined = mesh.merge(
        accessibility,
        left_on=osmid_col,
        right_index=True,
        how="left",
    )

    return (
        df[["geometry"]]
        .reset_index(names="orig_index")
        .sjoin(mesh_joined, how="left")
        .drop(columns=[osmid_col, "index_right", "geometry"])
        .groupby("orig_index")
        .mean()[f"jobs_{item_key}"]
    )


def calculate_aggregate(
    results: list[tuple[str, pd.Series]],
) -> dict:
    return pd.concat([result for _, result in results], axis=1).to_dict(orient="index")


@metric(
    name="accessibility_jobs",
    description=(
        "Computes, for each spatial unit and requested DENUE industry group, the "
        "mean number of estimated workers reachable through the OpenStreetMap "
        "road network. This number is weighted exponentially and time-decayed "
        "or distance-decayed (depending on the edge_weights parameter). "
        "Results are weighted job-accessibility scores, not counts of jobs located "
        "inside each spatial unit."
    ),
    inputs={
        "patterns": BatchInput(
            max_items=20,
            allow_labels=True,
            items=Input(
                description=(
                    "Regex pattern to match against the SCIAN/NAICS "
                    "6-digit code. Only jobs matching the pattern will be "
                    "counted in the accessibility score."
                ),
                examples=[r"^31\d{4}$", r"^311\d{3}$", r"^3111\d{2}$"],
            ),
        ),
        "year": Input(description="Year of the DENUE data to use."),
        "month": Input(
            description=(
                "Month of the DENUE data to use. If not provided, defaults to May "
                "for 2025 and November for all other years."
            ),
        ),
        "network_type": Input(
            description="Type of network to use for accessibility calculations.",
        ),
        "edge_weights": Input(
            description=(
                "Type of edge weights to use for accessibility calculations. "
                "'length' uses the length of the road segments, while 'travel_time' "
                "uses the estimated travel time based on speed limits (or walking "
                "speed if walking network is used)."
            ),
        ),
        "max_weight": Input(
            description=(
                "Maximum weight (in meters or seconds) for the accessibility "
                "calculation. Nodes beyond this weight from the source will not be "
                "considered reachable."
            ),
            ge=0,
        ),
    },
    output=TableOutputV4(
        kind="table",
        batched_columns=[
            BatchedTableOutputColumnV4(
                source="patterns",
                name="jobs_{key}",
                description=(
                    "Accessibility score derived from the number of reachable "
                    "workers in the DENUE dataset, weighted by distance or time, "
                    "for the specified SCIAN/NAICS pattern."
                ),
                type="number",
                unit="dimensionless",
                nullable=False,
            )
        ],
    ),
)
def metric(  # noqa: PLR0913
    location: LocationInput,
    patterns: list[BatchItem[str]],
    year: Literal[2020, 2021, 2022, 2023, 2024, 2025],
    max_weight: float,
    month: Literal[5, 11] | None = None,
    edge_weights: Literal["length", "travel_time"] = "travel_time",
    network_type: Literal["drive", "walk"] = "drive",
    *,
    context: RunContext,
) -> TableJobResult | FailedJobResult:
    df = convert_geojson_to_gdf(location).to_crs(WANTED_CRS)
    bounds = Bounds(*df["geometry"].buffer(10_000).total_bounds)

    try:
        nets = get_networks(bounds)
        context.report_message("Loaded networks")

        denue = get_denue(
            bounds,
            context.db,
            year=year,
            month=month,
            nets=nets,
        )
        context.report_message("Loaded DENUE data")

        mesh = get_mesh(bounds, context.db, nets=nets)
        context.report_message("Loaded mesh data")

        series: list[pd.Series] = []
        for i, batch_item in enumerate(patterns):
            series.append(
                calculate_for_items(
                    batch_item.key,
                    df=df,
                    denue=denue,
                    mesh=mesh,
                    nets=nets,
                    network_type=network_type,
                    pattern=batch_item.value,
                    max_weight=max_weight,
                    edge_weights=edge_weights,
                )
            )
            context.report_progress(
                stage="batch_items", current=i, total=len(patterns), unit="items"
            )
    except (TypeError, ValueError, ValidationError) as exc:
        return FailedJobResult(
            job_id=context.job_id, error={"type": "validation", "message": str(exc)}
        )

    return TableJobResult.from_dataframe(context.job_id, pd.concat(series, axis=1))
