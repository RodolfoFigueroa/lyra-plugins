import ee
from lyra.sdk.context import RunContext
from lyra.sdk.models import JobEnvelope, TableJobResult
from lyra.utils.ee import reduce_ee_image_over_gdf_factory

from lyra_plugins.functions.tree_coverage import load_tree_coverage_img
from lyra_plugins.runners.common import parse_location, result_from_column_mapping

calculate = reduce_ee_image_over_gdf_factory(
    lambda bbox: (
        load_tree_coverage_img(bbox)
        .gte(ee.Number(3))
        .multiply(ee.image.Image.pixelArea())
    ),
    reducer=ee.Reducer.sum(),
    scale=25,
)


def run(job: JobEnvelope, context: RunContext) -> TableJobResult:
    context.emit_event("progress", {"message": "Computing tree coverage"})
    context.check_cancelled()

    location = parse_location(job)
    values = calculate(location)
    return result_from_column_mapping(job, location, "tree_coverage_m2", values)
