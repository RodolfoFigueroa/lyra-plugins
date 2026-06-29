from lyra.sdk.context import RunContext
from lyra.sdk.models import FileJobResult, JobEnvelope
from lyra.utils.ee import convert_polygon_to_ee
from lyra.utils.geometry import convert_geojson_to_gdf

from lyra_plugins.functions.base import download_ee_image
from lyra_plugins.functions.tree_coverage import load_tree_coverage_fraction_img
from lyra_plugins.runners.common import output_path, parse_bounds


def run(job: JobEnvelope, context: RunContext) -> FileJobResult:
    context.emit_event("progress", {"message": "Preparing tree coverage raster"})
    context.check_cancelled()

    bounds_geojson = parse_bounds(job)
    gdf = convert_geojson_to_gdf(bounds_geojson).to_crs("EPSG:4326")
    bounds = convert_polygon_to_ee(gdf["geometry"].iloc[0])
    img = load_tree_coverage_fraction_img(
        bounds,
        min_tree_height=job.input.get("min_tree_height", 3),
    )

    path = output_path(context, "tree_coverage_raster.tif")
    download_ee_image(
        img,
        bounds,
        path,
        download_kwargs={
            "dtype": "float32",
            "crs": job.input.get("crs", "EPSG:4326"),
            "scale": job.input.get("scale", 10),
            "resampling": "near",
        },
    )
    return FileJobResult(
        job_id=job.job_id, file_path=str(path), media_type="image/tiff"
    )
