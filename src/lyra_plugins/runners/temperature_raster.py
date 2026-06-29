from lyra.sdk.context import RunContext
from lyra.sdk.models import FileJobResult, JobEnvelope
from lyra.utils.date import get_season_date_range
from lyra.utils.ee import convert_polygon_to_ee
from lyra.utils.geometry import convert_geojson_to_gdf

from lyra_plugins.functions.base import download_ee_image
from lyra_plugins.functions.temperature import reduce_landsat_collection
from lyra_plugins.runners.common import output_path, parse_bounds


def run(job: JobEnvelope, context: RunContext) -> FileJobResult:
    context.emit_event("progress", {"message": "Preparing temperature raster"})
    context.check_cancelled()

    bounds_geojson = parse_bounds(job)
    gdf = convert_geojson_to_gdf(bounds_geojson).to_crs("EPSG:4326")
    bounds = convert_polygon_to_ee(gdf["geometry"].iloc[0])

    start_date, end_date = get_season_date_range(job.input["season"], job.input["year"])
    img = reduce_landsat_collection(
        bounds,
        start_date,
        end_date,
        col_idx=8 if job.input["year"] < 2022 else 9,
    )

    path = output_path(context, "temperature_raster.tif")
    download_ee_image(
        img,
        bounds,
        path,
        download_kwargs={
            "dtype": "float32",
            "crs": job.input.get("crs", "EPSG:4326"),
            "scale": job.input.get("scale", 30),
            "resampling": "near",
        },
    )
    return FileJobResult(
        job_id=job.job_id, file_path=str(path), media_type="image/tiff"
    )
