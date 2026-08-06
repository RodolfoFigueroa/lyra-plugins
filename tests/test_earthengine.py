import os
from pathlib import Path
from typing import TYPE_CHECKING, Self, cast

import numpy as np
import pytest
import rasterio as rio
from rasterio import Affine

from lyra_plugins.functions import earthengine

if TYPE_CHECKING:
    from collections.abc import Callable

    import ee


class _FakeImage:
    def __init__(self) -> None:
        self.unmask_calls: list[tuple[float, bool]] = []

    def clip(self, _bounds: object) -> Self:
        return self

    def unmask(self, value: float, **kwargs: bool) -> Self:
        self.unmask_calls.append((value, kwargs["sameFootprint"]))
        return self


class _FakePrepared:
    def __init__(self, kwargs: dict[str, object], tile_number: int = 0) -> None:
        self.kwargs = kwargs
        self.tile_number = tile_number


class _FakeAccessor:
    tile_number = 0
    fail_on_tile: int | None = None
    template_count = 1
    template_shape = (5, 7)
    template_transform = Affine(10, 0, 100, 0, -10, 200)

    def __init__(self, image: object) -> None:
        self.image = image
        self.__dict__["prepareForExport"] = self.prepare_for_export
        self.__dict__["toGeoTIFF"] = self.to_geotiff

    @property
    def count(self) -> int:
        return self.template_count

    @property
    def shape(self) -> tuple[int, int]:
        return self.template_shape

    @property
    def crs(self) -> str:
        return "EPSG:3857"

    @property
    def transform(self) -> tuple[float, ...]:
        return self.template_transform[:6]

    @property
    def nodata(self) -> float:
        return -9999.0

    @property
    def profile(self) -> dict[str, object]:
        return {
            "width": self.template_shape[1],
            "height": self.template_shape[0],
            "count": 1,
            "dtype": "float32",
            "crs": self.crs,
            "transform": self.template_transform,
            "nodata": -9999.0,
        }

    def prepare_for_export(self, **kwargs: object) -> _FakePrepared:
        if "region" in kwargs:
            return _FakePrepared(dict(kwargs))
        type(self).tile_number += 1
        return _FakePrepared(dict(kwargs), type(self).tile_number)

    def to_geotiff(self, file: os.PathLike | str, **_kwargs: object) -> None:
        prepared = cast("_FakePrepared", self.image)
        if prepared.tile_number == self.fail_on_tile:
            msg = "simulated tile failure"
            raise RuntimeError(msg)

        shape = cast("tuple[int, int]", prepared.kwargs["shape"])
        transform_values = cast(
            "tuple[float, ...]",
            prepared.kwargs["crs_transform"],
        )
        with rio.open(
            file,
            "w",
            driver="GTiff",
            width=shape[1],
            height=shape[0],
            count=1,
            dtype="float32",
            crs=cast("str", prepared.kwargs["crs"]),
            transform=Affine(*transform_values),
        ) as dst:
            dst.write(
                np.full(shape, prepared.tile_number, dtype="float32"),
                1,
            )


@pytest.fixture(autouse=True)
def _reset_fake_accessor() -> None:
    _FakeAccessor.tile_number = 0
    _FakeAccessor.fail_on_tile = None
    _FakeAccessor.template_count = 1


def _install_fakes(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    computation_regions: list[object] = []
    monkeypatch.setattr(earthengine, "ImageAccessor", _FakeAccessor)
    monkeypatch.setattr(
        earthengine,
        "_window_geometry",
        lambda window, *_args, **_kwargs: computation_regions.append(window) or window,
    )
    return computation_regions


def test_chunked_download_writes_aligned_windows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    computation_regions = _install_fakes(monkeypatch)
    factory_regions: list[object] = []

    def image_factory(region: object, _output_bounds: object) -> _FakeImage:
        factory_regions.append(region)
        return _FakeImage()

    output = tmp_path / "output.tif"
    earthengine.download_chunked_ee_image(
        cast("Callable[[ee.Geometry, ee.Geometry], ee.Image]", image_factory),
        cast("ee.Geometry", object()),
        output,
        {"crs": "EPSG:3857", "dtype": "float32", "scale": 10},
        max_chunk_size_m=20,
    )

    expected = np.array(
        [
            [1, 1, 2, 2, 3, 3, 4],
            [1, 1, 2, 2, 3, 3, 4],
            [5, 5, 6, 6, 7, 7, 8],
            [5, 5, 6, 6, 7, 7, 8],
            [9, 9, 10, 10, 11, 11, 12],
        ],
        dtype="float32",
    )
    with rio.open(output) as src:
        np.testing.assert_array_equal(src.read(1), expected)
        np.testing.assert_equal(src.transform, _FakeAccessor.template_transform)
        np.testing.assert_equal(src.crs, rio.CRS.from_epsg(3857))
        np.testing.assert_equal(src.nodata, -9999.0)

    np.testing.assert_equal(len(computation_regions), 12)
    np.testing.assert_equal(len(factory_regions), 13)
    np.testing.assert_equal(list(tmp_path.glob(".output.tif.*.tmp")), [])


def test_chunked_download_preserves_destination_after_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fakes(monkeypatch)
    _FakeAccessor.fail_on_tile = 2
    output = tmp_path / "output.tif"
    output.write_bytes(b"original")

    with pytest.raises(RuntimeError, match="simulated tile failure"):
        earthengine.download_chunked_ee_image(
            cast(
                "Callable[[ee.Geometry, ee.Geometry], ee.Image]",
                lambda _region, _output_bounds: _FakeImage(),
            ),
            cast("ee.Geometry", object()),
            output,
            {"crs": "EPSG:3857", "dtype": "float32", "scale": 10},
            max_chunk_size_m=20,
        )

    np.testing.assert_equal(output.read_bytes(), b"original")
    np.testing.assert_equal(list(tmp_path.glob(".output.tif.*.tmp")), [])


@pytest.mark.parametrize("scale", [None, True, 0, -1, "10", np.nan, np.inf])
def test_chunked_download_rejects_invalid_scale(scale: object) -> None:
    with pytest.raises(ValueError, match="positive numeric 'scale'"):
        earthengine.download_chunked_ee_image(
            cast(
                "Callable[[ee.Geometry, ee.Geometry], ee.Image]",
                lambda _region, _output_bounds: _FakeImage(),
            ),
            cast("ee.Geometry", object()),
            Path("unused.tif"),
            {"scale": scale},
        )


@pytest.mark.parametrize("chunk_size", [0, -1, np.nan, np.inf])
def test_chunked_download_rejects_invalid_chunk_size(chunk_size: float) -> None:
    with pytest.raises(ValueError, match="max_chunk_size_m must be positive"):
        earthengine.download_chunked_ee_image(
            cast(
                "Callable[[ee.Geometry, ee.Geometry], ee.Image]",
                lambda _region, _output_bounds: _FakeImage(),
            ),
            cast("ee.Geometry", object()),
            Path("unused.tif"),
            {"scale": 10},
            max_chunk_size_m=chunk_size,
        )


def test_chunked_download_rejects_multiband_image(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fakes(monkeypatch)
    _FakeAccessor.template_count = 2

    with pytest.raises(ValueError, match="exactly one image band"):
        earthengine.download_chunked_ee_image(
            cast(
                "Callable[[ee.Geometry, ee.Geometry], ee.Image]",
                lambda _region, _output_bounds: _FakeImage(),
            ),
            cast("ee.Geometry", object()),
            tmp_path / "unused.tif",
            {"scale": 10},
        )
