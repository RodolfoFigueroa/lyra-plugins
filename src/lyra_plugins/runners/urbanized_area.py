from collections.abc import Mapping

from lyra.sdk.context import RunContext
from lyra.sdk.models import JobEnvelope, TableJobResult
from lyra.sdk.models.geometry import GeoJSON

from lyra_plugins.runners.common import parse_location, result_from_column_mapping


def calculate_urbanized_area(
    location: GeoJSON,
) -> Mapping[str, float | int | str | bool | None]:
    from lyra_plugins.processors import urbanized_area  # noqa: PLC0415

    return urbanized_area.calculate(location)


def run(job: JobEnvelope, context: RunContext) -> TableJobResult:
    context.emit_event("progress", {"message": "Computing urbanized area"})
    context.check_cancelled()

    location = parse_location(job)
    values = calculate_urbanized_area(location)
    return result_from_column_mapping(job, location, "urbanized_area_m2", values)
