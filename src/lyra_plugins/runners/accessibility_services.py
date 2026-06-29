from collections.abc import Mapping
from typing import Any, Literal

import pandas as pd
from lyra.sdk.context import RunContext
from lyra.sdk.models import FailedJobResult, JobEnvelope, TableJobResult
from lyra.sdk.models.geometry import GeoJSON
from pydantic import ValidationError

from lyra_plugins.models.accessibility_services import AmenityGroupModel
from lyra_plugins.processors import accessibility_services
from lyra_plugins.runners.common import (
    BatchItem,
    failed,
    parse_location,
    result_from_series_batch,
    validate_unique_batch_keys,
)


def _month(input_payload: Mapping[str, Any]) -> Literal[5, 11] | None:
    value = input_payload.get("month")
    if value is None:
        return None
    return value


def _make_item(
    input_payload: Mapping[str, Any],
    batch_item: BatchItem,
) -> AmenityGroupModel:
    value = batch_item["value"]
    if not isinstance(value, Mapping):
        msg = "Service filter value must be an object."
        raise TypeError(msg)
    return AmenityGroupModel(
        amenities=value["amenities"],
        attraction_edge_weights=input_payload.get("attraction_edge_weights", "length"),
        attraction_max_weight=input_payload.get("attraction_max_weight", 1000),
        accessibility_edge_weights=input_payload.get(
            "accessibility_edge_weights",
            "length",
        ),
        accessibility_max_weight=input_payload.get("accessibility_max_weight", 1000),
        network_type=input_payload.get("network_type", "drive"),
    )


def _series_for_item(
    key: str,
    item: AmenityGroupModel,
    prepared: Mapping[str, Any],
) -> pd.Series:
    return accessibility_services.calculate_for_items(key, item, **prepared).rename(
        f"accessibility_{key}",
    )


def run_with_public_spaces(
    job: JobEnvelope,
    context: RunContext,
    public_spaces: GeoJSON | None,
) -> TableJobResult | FailedJobResult:
    context.emit_event("progress", {"message": "Preparing service accessibility"})
    context.check_cancelled()

    if context.db is None:
        return failed(job, "configuration", "Database is unavailable.")

    location = parse_location(job)
    service_filters: list[BatchItem] = job.input["service_filters"]
    duplicate_error = validate_unique_batch_keys(job, service_filters)
    if duplicate_error is not None:
        return duplicate_error

    try:
        prepared = accessibility_services.calculate_prepare(
            location,
            context.db,
            data_public=public_spaces,
            year=job.input.get("year", 2025),
            month=_month(job.input),
        )
        series = [
            _series_for_item(
                batch_item["key"],
                _make_item(job.input, batch_item),
                prepared,
            )
            for batch_item in service_filters
        ]
    except (TypeError, ValueError, ValidationError) as exc:
        return failed(job, "validation", str(exc))

    return result_from_series_batch(job, location, series)


def run(job: JobEnvelope, context: RunContext) -> TableJobResult | FailedJobResult:
    return run_with_public_spaces(job, context, public_spaces=None)
