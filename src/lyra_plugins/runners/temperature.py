from lyra.sdk.context import RunContext
from lyra.sdk.models import JobEnvelope, TableJobResult

from lyra_plugins.processors import temperature
from lyra_plugins.runners.common import parse_location, result_from_column_mapping


def run(job: JobEnvelope, context: RunContext) -> TableJobResult:
    context.emit_event("progress", {"message": "Computing temperature"})
    context.check_cancelled()

    location = parse_location(job)
    values = temperature.calculate(
        location,
        year=job.input["year"],
        season=job.input["season"],
    )
    return result_from_column_mapping(job, location, "temperature_c", values)
