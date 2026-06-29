from collections.abc import Mapping

from lyra.sdk.context import RunContext
from lyra.sdk.models import JobEnvelope, TableJobResult
from lyra.sdk.models.geometry import GeoJSON

from lyra_plugins.runners.common import parse_location, result_from_column_mapping


def calculate_tree_coverage(
    location: GeoJSON,
) -> Mapping[str, float | int | str | bool | None]:
    from lyra_plugins.processors import tree_coverage  # noqa: PLC0415

    return tree_coverage.calculate(location)


def run(job: JobEnvelope, context: RunContext) -> TableJobResult:
    context.emit_event("progress", {"message": "Computing tree coverage"})
    context.check_cancelled()

    location = parse_location(job)
    values = calculate_tree_coverage(location)
    return result_from_column_mapping(job, location, "tree_coverage_m2", values)
