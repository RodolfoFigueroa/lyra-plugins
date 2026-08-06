import math
import os
import tempfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import ee
import numpy as np
import rasterio as rio
from geedim.image import ImageAccessor
from rasterio import Affine
from rasterio.io import DatasetWriter
from rasterio.windows import Window
from rasterio.windows import bounds as window_bounds
from rasterio.windows import transform as window_transform

_GEEDIM_TO_GEOTIFF_KWARGS = frozenset(
    {
        "driver",
        "max_cpus",
        "max_requests",
        "max_tile_bands",
        "max_tile_dim",
        "max_tile_size",
        "nodata",
    }
)
_ImageFactory = Callable[[ee.Geometry, ee.Geometry], ee.Image]


def download_ee_image(
    img: ee.Image,
    bounds: ee.Geometry | ee.FeatureCollection,
    fpath: os.PathLike,
    download_kwargs: dict,
) -> None:
    export_kwargs = dict(download_kwargs)
    if bounds is not None:
        export_kwargs["region"] = bounds

    export_kwargs.pop("num_threads", None)
    unmask_value = export_kwargs.pop("unmask_value", None)
    if unmask_value is not None:
        if isinstance(bounds, ee.Geometry):
            img = img.clip(bounds)
        elif isinstance(bounds, ee.FeatureCollection):
            img = img.clipToCollection(bounds)
        img = img.unmask(unmask_value, sameFootprint=False)

    to_geotiff_kwargs = {"overwrite": export_kwargs.pop("overwrite", True)}
    for key in _GEEDIM_TO_GEOTIFF_KWARGS:
        if key in export_kwargs:
            to_geotiff_kwargs[key] = export_kwargs.pop(key)

    with tempfile.NamedTemporaryFile(suffix=".tif") as tmp:
        prepared_img = ImageAccessor(img).prepareForExport(**export_kwargs)
        ImageAccessor(prepared_img).toGeoTIFF(tmp.name, **to_geotiff_kwargs)

        with rio.open(tmp.name) as src:
            profile = src.profile
            profile.update(
                count=1,
                compress="lzw",
            )

            with rio.open(fpath, "w", **profile) as dst:
                dst.write(src.read(1), 1)


def _chunk_windows(
    shape: tuple[int, int],
    max_chunk_dim: int,
) -> Iterator[Window]:
    height, width = shape
    for row_off in range(0, height, max_chunk_dim):
        for col_off in range(0, width, max_chunk_dim):
            yield Window.from_slices(
                (row_off, min(row_off + max_chunk_dim, height)),
                (col_off, min(col_off + max_chunk_dim, width)),
            )


def _window_geometry(
    window: Window,
    transform: Affine,
    crs: str,
    *,
    halo: int = 0,
    image_shape: tuple[int, int] | None = None,
) -> ee.Geometry:
    if halo:
        if image_shape is None:
            msg = "image_shape is required when halo is non-zero"
            raise ValueError(msg)
        image_height, image_width = image_shape
        col_off = max(int(window.col_off) - halo, 0)
        row_off = max(int(window.row_off) - halo, 0)
        col_stop = min(int(window.col_off + window.width) + halo, image_width)
        row_stop = min(int(window.row_off + window.height) + halo, image_height)
        window = Window.from_slices(
            (row_off, row_stop),
            (col_off, col_stop),
        )

    left, bottom, right, top = window_bounds(window, transform)
    return ee.Geometry.Rectangle(
        [left, bottom, right, top],
        proj=ee.Projection(crs),
        geodesic=False,
    )


def _split_download_kwargs(
    download_kwargs: dict,
) -> tuple[dict, dict, float | None]:
    export_kwargs = dict(download_kwargs)
    export_kwargs.pop("num_threads", None)
    unmask_value = export_kwargs.pop("unmask_value", None)
    to_geotiff_kwargs = {"overwrite": export_kwargs.pop("overwrite", True)}
    for key in _GEEDIM_TO_GEOTIFF_KWARGS:
        if key in export_kwargs:
            to_geotiff_kwargs[key] = export_kwargs.pop(key)
    return export_kwargs, to_geotiff_kwargs, unmask_value


def _prepare_chunk_image(
    image_factory: _ImageFactory,
    computation_bounds: ee.Geometry,
    output_bounds: ee.Geometry,
    unmask_value: float | None,
) -> ee.Image:
    image = image_factory(computation_bounds, output_bounds).clip(output_bounds)
    if unmask_value is not None:
        image = image.unmask(unmask_value, sameFootprint=False)
    return image


@dataclass(frozen=True)
class _ChunkPlan:
    image_factory: _ImageFactory
    bounds: ee.Geometry
    shape: tuple[int, int]
    crs: str
    transform: Affine
    export_kwargs: dict
    to_geotiff_kwargs: dict
    unmask_value: float | None
    max_chunk_dim: int


def _download_chunk(
    image: ee.Image,
    window: Window,
    plan: _ChunkPlan,
) -> np.ndarray:
    tile_export_kwargs = {
        key: value
        for key, value in plan.export_kwargs.items()
        if key not in {"crs", "region", "scale"}
    }
    tile_export_kwargs.update(
        crs=plan.crs,
        crs_transform=window_transform(window, plan.transform)[:6],
        shape=(int(window.height), int(window.width)),
    )
    prepared_tile = ImageAccessor(image).prepareForExport(**tile_export_kwargs)

    with tempfile.NamedTemporaryFile(suffix=".tif") as tile_file:
        ImageAccessor(prepared_tile).toGeoTIFF(
            tile_file.name,
            **plan.to_geotiff_kwargs,
        )
        with rio.open(tile_file.name) as src:
            return src.read(1)


def _write_chunks(
    dst: DatasetWriter,
    plan: _ChunkPlan,
) -> None:
    for window in _chunk_windows(plan.shape, plan.max_chunk_dim):
        compute_region = _window_geometry(
            window,
            plan.transform,
            plan.crs,
            halo=1,
            image_shape=plan.shape,
        )
        tile_image = _prepare_chunk_image(
            plan.image_factory,
            compute_region,
            plan.bounds,
            plan.unmask_value,
        )
        tile_array = _download_chunk(
            tile_image,
            window,
            plan,
        )
        dst.write(tile_array, 1, window=window)


def download_chunked_ee_image(
    image_factory: _ImageFactory,
    bounds: ee.Geometry,
    fpath: os.PathLike,
    download_kwargs: dict,
    *,
    max_chunk_size_m: float = 5_000,
) -> None:
    """Download an image built in bounded computation chunks on one output grid.

    ``image_factory`` receives the expanded computation bounds followed by the
    original output bounds.  Operations such as ``reduceResolution`` should clip
    their source pixels to the output bounds before reducing so pixels outside the
    area of interest do not influence border values.
    """
    export_kwargs, to_geotiff_kwargs, unmask_value = _split_download_kwargs(
        download_kwargs
    )
    scale = export_kwargs.get("scale")
    if (
        not isinstance(scale, int | float)
        or isinstance(scale, bool)
        or not math.isfinite(scale)
        or scale <= 0
    ):
        msg = "download_kwargs must contain a positive numeric 'scale'"
        raise ValueError(msg)
    if not math.isfinite(max_chunk_size_m) or max_chunk_size_m <= 0:
        msg = "max_chunk_size_m must be positive"
        raise ValueError(msg)

    template_image = _prepare_chunk_image(
        image_factory,
        bounds,
        bounds,
        unmask_value,
    )
    export_kwargs["region"] = bounds
    prepared_template = ImageAccessor(template_image).prepareForExport(**export_kwargs)
    template = ImageAccessor(prepared_template)
    if template.count != 1:
        msg = "Chunked Earth Engine downloads support exactly one image band"
        raise ValueError(msg)
    shape = template.shape
    crs = template.crs
    transform_values = template.transform
    profile = template.profile
    if shape is None or crs is None or transform_values is None or profile is None:
        msg = "Prepared Earth Engine image does not define a complete output grid"
        raise ValueError(msg)

    max_chunk_dim = max(int(max_chunk_size_m // scale), 1)
    transform = Affine(*transform_values)
    output_path = Path(fpath)
    overwrite = bool(to_geotiff_kwargs.pop("overwrite"))
    if output_path.exists() and not overwrite:
        msg = f"File exists: '{output_path}'."
        raise FileExistsError(msg)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix=f".{output_path.name}.",
        suffix=".tmp",
        dir=output_path.parent,
        delete=False,
    ) as temp_output:
        temp_output_path = Path(temp_output.name)

    nodata = to_geotiff_kwargs.get("nodata", True)
    if nodata is True:
        nodata = template.nodata
    elif nodata is False:
        nodata = None
    profile.update(driver="GTiff", count=1, compress="lzw", nodata=nodata)
    plan = _ChunkPlan(
        image_factory=image_factory,
        bounds=bounds,
        shape=shape,
        crs=crs,
        transform=transform,
        export_kwargs=export_kwargs,
        to_geotiff_kwargs={**to_geotiff_kwargs, "overwrite": True},
        unmask_value=unmask_value,
        max_chunk_dim=max_chunk_dim,
    )

    try:
        with rio.open(temp_output_path, "w", **profile) as dst:
            _write_chunks(dst, plan)

        temp_output_path.replace(output_path)
    except BaseException:
        temp_output_path.unlink(missing_ok=True)
        raise
