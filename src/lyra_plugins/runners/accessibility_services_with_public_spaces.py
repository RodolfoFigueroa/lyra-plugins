from lyra.sdk.context import RunContext
from lyra.sdk.models import FailedJobResult, JobEnvelope, TableJobResult
from lyra.sdk.models.geometry import GeoJSON

from lyra_plugins.runners.accessibility_services import run_with_public_spaces


def run(job: JobEnvelope, context: RunContext) -> TableJobResult | FailedJobResult:
    public_spaces = GeoJSON.model_validate(job.input["public_spaces"])
    return run_with_public_spaces(job, context, public_spaces=public_spaces)
