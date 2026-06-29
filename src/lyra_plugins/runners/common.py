from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pandas as pd
from lyra.sdk.context import RunContext
from lyra.sdk.models import FailedJobResult, JobEnvelope, TableJobResult
from lyra.sdk.models.geometry import GeoJSON, SingleGeoJSON

BatchItem = Mapping[str, Any]


def failed(job: JobEnvelope, error_type: str, message: str) -> FailedJobResult:
    return FailedJobResult(
        job_id=job.job_id,
        error={"type": error_type, "message": message},
    )


def parse_location(job: JobEnvelope, field: str = "location") -> GeoJSON:
    return GeoJSON.model_validate(job.input[field])


def parse_bounds(job: JobEnvelope, field: str = "bounds") -> SingleGeoJSON:
    return SingleGeoJSON.model_validate(job.input[field])


def feature_ids(location: GeoJSON) -> list[str]:
    return [str(feature.id) for feature in location.features]


def validate_unique_batch_keys(
    job: JobEnvelope,
    items: Sequence[BatchItem],
) -> FailedJobResult | None:
    keys = [item.get("key") for item in items]
    if len(keys) != len(set(keys)):
        return failed(job, "validation", "Batched item keys must be unique.")
    return None


def result_from_column_mapping(
    job: JobEnvelope,
    location: GeoJSON,
    column: str,
    values: Mapping[str, float | int | str | bool | None],
) -> TableJobResult:
    return TableJobResult.from_mapping(
        job_id=job.job_id,
        input_index=feature_ids(location),
        columns=[column],
        values={column: values},
    )


def result_from_series(
    job: JobEnvelope,
    location: GeoJSON,
    series: pd.Series,
    name: str,
) -> TableJobResult:
    ordered = series.rename(name).reindex(feature_ids(location))
    return TableJobResult.from_series(
        job_id=job.job_id,
        series=ordered,
        name=name,
    )


def result_from_series_batch(
    job: JobEnvelope,
    location: GeoJSON,
    series_batch: Iterable[pd.Series],
) -> TableJobResult:
    table = pd.concat(list(series_batch), axis=1).reindex(feature_ids(location))
    return TableJobResult.from_dataframe(job_id=job.job_id, dataframe=table)


def output_path(context: RunContext, filename: str) -> Path:
    return context.temp_dir / filename
