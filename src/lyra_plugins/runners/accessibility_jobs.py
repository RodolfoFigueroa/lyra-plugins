from collections.abc import Mapping
from typing import Any, Literal

import pandas as pd
from lyra.sdk.context import RunContext
from lyra.sdk.models import FailedJobResult, JobEnvelope, TableJobResult
from pydantic import ValidationError

from lyra_plugins.models.accessibility_jobs import JobGroupModel
from lyra_plugins.processors import accessibility_jobs
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
    input_payload: Mapping[str, Any], batch_item: BatchItem
) -> JobGroupModel:
    return JobGroupModel(
        pattern=batch_item["value"],
        edge_weights=input_payload.get("edge_weights", "length"),
        max_weight=input_payload.get("max_weight", 1000),
        network_type=input_payload.get("network_type", "drive"),
    )


def _series_for_item(
    key: str,
    item: JobGroupModel,
    prepared: Mapping[str, Any],
) -> pd.Series:
    result = accessibility_jobs.calculate_for_items(key, item, **prepared)
    if isinstance(result, pd.DataFrame):
        return result.iloc[:, 0].rename(f"jobs_{key}")
    return result.rename(f"jobs_{key}")


def run(job: JobEnvelope, context: RunContext) -> TableJobResult | FailedJobResult:
    context.emit_event("progress", {"message": "Preparing job accessibility"})
    context.check_cancelled()

    if context.db is None:
        return failed(job, "configuration", "Database is unavailable.")

    location = parse_location(job)
    patterns: list[BatchItem] = job.input["patterns"]
    duplicate_error = validate_unique_batch_keys(job, patterns)
    if duplicate_error is not None:
        return duplicate_error

    try:
        prepared = accessibility_jobs.calculate_prepare(
            location,
            context.db,
            year=job.input.get("year", 2025),
            month=_month(job.input),
        )
        series = [
            _series_for_item(
                batch_item["key"],
                _make_item(job.input, batch_item),
                prepared,
            )
            for batch_item in patterns
        ]
    except (TypeError, ValueError, ValidationError) as exc:
        return failed(job, "validation", str(exc))

    return result_from_series_batch(job, location, series)
