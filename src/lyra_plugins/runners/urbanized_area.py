import ee
from lyra.sdk.context import RunContext
from lyra.sdk.models import JobEnvelope, TableJobResult
from lyra.utils.ee import reduce_ee_image_over_gdf_factory

from lyra_plugins.runners.common import parse_location, result_from_column_mapping


def load_urbanized_area_img(bbox: ee.Geometry) -> ee.Image:
    return (
        ee.ImageCollection("JRC/GHSL/P2023A/GHS_BUILT_S")
        .select("built_surface")
        .filterBounds(bbox)
        .mean()
    )


calculate = reduce_ee_image_over_gdf_factory(
    load_urbanized_area_img,
    reducer=ee.Reducer.sum(),
    scale=100,
)


def run(job: JobEnvelope, context: RunContext) -> TableJobResult:
    context.emit_event("progress", {"message": "Computing urbanized area"})
    context.check_cancelled()

    location = parse_location(job)
    values = calculate(location)
    return result_from_column_mapping(job, location, "urbanized_area_m2", values)
