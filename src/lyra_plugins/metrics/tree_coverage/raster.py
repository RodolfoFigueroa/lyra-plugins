from lyra.sdk import BoundsInput
from lyra.sdk.context import RunContext
from lyra.sdk.models import FileJobResult
from lyra.utils.ee import convert_polygon_to_ee
from lyra.utils.geometry import convert_geojson_to_gdf

from lyra_plugins.functions.earthengine import download_chunked_ee_image
from lyra_plugins.metrics.tree_coverage.common import load_tree_coverage_fraction_img


def run(
    location: BoundsInput,
    min_tree_height: int = 3,
    crs: str = "EPSG:4326",
    scale: int = 10,
    *,
    context: RunContext,
) -> FileJobResult:
    gdf = convert_geojson_to_gdf(location).to_crs("EPSG:4326")
    bounds = convert_polygon_to_ee(gdf["geometry"].iloc[0])
    path = context.temp_dir / "tree_coverage_raster.tif"
    download_chunked_ee_image(
        lambda computation_bounds, output_bounds: load_tree_coverage_fraction_img(
            computation_bounds,
            min_tree_height=min_tree_height,
            clip_bounds=output_bounds,
        ),
        bounds,
        path,
        download_kwargs={
            "dtype": "float32",
            "crs": crs,
            "scale": scale,
            "resampling": "near",
        },
    )
    return FileJobResult(
        job_id=context.job_id,
        file_path=str(path),
        media_type="image/tiff",
    )
