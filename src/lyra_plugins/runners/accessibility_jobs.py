from collections.abc import Mapping
from typing import Any, Literal, NamedTuple

import geopandas as gpd
import pandarm as pdna
import pandas as pd
from lyra.sdk import LyraDB
from lyra.sdk.context import RunContext
from lyra.sdk.models import FailedJobResult, JobEnvelope, TableJobResult
from lyra.utils.geometry import convert_geojson_to_gdf
from pydantic import ValidationError

from lyra_plugins.constants import PER_OCU_TO_NUM_WORKERS_MAP
from lyra_plugins.functions.base import get_geometries_osmid
from lyra_plugins.functions.osm import load_accessibility_net_from_bounds
from lyra_plugins.models.accessibility_jobs import JobGroupModel
from lyra_plugins.runners.common import (
    BatchItem,
    failed,
    parse_location,
    result_from_series_batch,
)

WANTED_CRS = "EPSG:6372"


class Networks(NamedTuple):
    drive: pdna.Network
    walk: pdna.Network


def _make_item(
    input_payload: Mapping[str, Any], batch_item: BatchItem
) -> JobGroupModel:
    return JobGroupModel(
        pattern=batch_item["value"],
        edge_weights=input_payload.get("edge_weights", "length"),
        max_weight=input_payload.get("max_weight", 1000),
        network_type=input_payload.get("network_type", "drive"),
    )


def get_networks(
    xmin: float,
    ymin: float,
    xmax: float,
    ymax: float,
) -> Networks:
    return Networks(
        **{
            network_type: load_accessibility_net_from_bounds(
                xmin,
                ymin,
                xmax,
                ymax,
                bounds_crs=WANTED_CRS,
                network_type=network_type,
            )
            for network_type in ("drive", "walk")
        }
    )


def get_denue(
    xmin: float,
    ymin: float,
    xmax: float,
    ymax: float,
    db: LyraDB,
    *,
    year: Literal[2020, 2021, 2022, 2023, 2024, 2025] = 2025,
    month: Literal[5, 11] | None,
    nets: Networks,
) -> gpd.GeoDataFrame:
    if month is None:
        month = 5 if year == 2025 else 11

    return (
        db.load_denue_from_bounds(xmin, ymin, xmax, ymax, year=year, month=month)
        .to_crs(WANTED_CRS)
        .assign(num_workers=lambda x: x["per_ocu"].map(PER_OCU_TO_NUM_WORKERS_MAP))
        .drop(columns=["per_ocu"])
        .assign(
            osmid_drive=lambda df: get_geometries_osmid(df, nets.drive),  # ty: ignore[invalid-argument-type]
            osmid_walk=lambda df: get_geometries_osmid(df, nets.walk),  # ty: ignore[invalid-argument-type]
        )
    )


def get_mesh(
    xmin: float,
    ymin: float,
    xmax: float,
    ymax: float,
    db: LyraDB,
    nets: Networks,
) -> gpd.GeoDataFrame:
    return db.load_mesh_from_bounds(xmin, ymin, xmax, ymax)[["geometry"]].assign(
        osmid_drive=lambda df: get_geometries_osmid(
            df,  # ty:ignore[invalid-argument-type]
            nets.drive,
        ),
        osmid_walk=lambda df: get_geometries_osmid(
            df,  # ty:ignore[invalid-argument-type]
            nets.walk,
        ),
    )


def calculate_for_items(
    item_key: str,
    *,
    df: gpd.GeoDataFrame,
    denue: gpd.GeoDataFrame,
    mesh: gpd.GeoDataFrame,
    nets: Networks,
    network_type: Literal["drive", "walk"],
    pattern: str,
    max_weight: float,
    edge_weights: Literal["length", "time"],
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

    # TODO: This mutates the network, which is not ideal. We should rewrite this.
    net_accessibility.set(
        denue_osmid_group.index,
        variable=denue_osmid_group.values,
        name=f"jobs_{item_key}",
    )

    mesh_joined = mesh.merge(
        net_accessibility.aggregate(
            max_weight,
            type="sum",
            decay="exp",
            name=f"jobs_{item_key}",
            imp_name=edge_weights,
        )
        .rename(f"jobs_{item_key}")
        .fillna(0),
        left_on=osmid_col,
        right_on="osmid",
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


def run(job: JobEnvelope, context: RunContext) -> TableJobResult | FailedJobResult:
    context.emit_event("progress", {"message": "Preparing job accessibility"})
    context.check_cancelled()

    if context.db is None:
        return failed(job, "configuration", "Database is unavailable.")

    location = parse_location(job)
    df = convert_geojson_to_gdf(location).to_crs(WANTED_CRS)
    xmin, ymin, xmax, ymax = df["geometry"].buffer(10_000).total_bounds

    try:
        nets = get_networks(xmin, ymin, xmax, ymax)
        denue = get_denue(
            xmin,
            ymin,
            xmax,
            ymax,
            context.db,
            year=job.input.get("year", 2025),
            month=job.input.get("month"),
            nets=nets,
        )
        mesh = get_mesh(xmin, ymin, xmax, ymax, context.db, nets=nets)

        series = [
            calculate_for_items(
                batch_item["key"],
                df=df,
                denue=denue,
                mesh=mesh,
                nets=nets,
                network_type=job.input["network_type"],
                pattern=batch_item["value"],
                max_weight=job.input["max_weight"],
                edge_weights=job.input["edge_weights"],
            )
            for batch_item in job.input["patterns"]
        ]
    except (TypeError, ValueError, ValidationError) as exc:
        return failed(job, "validation", str(exc))

    return result_from_series_batch(job, location, series)
