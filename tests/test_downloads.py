from pathlib import Path
from typing import TYPE_CHECKING, cast

import numpy as np
import pytest
import rasterio as rio
from rasterio.transform import from_origin

from lyra_plugins.functions import base

if TYPE_CHECKING:
    import ee


def test_download_ee_image_uses_geedim_accessor(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, object, dict[str, object]]] = []

    class FakeImageAccessor:
        def __init__(self, image: object) -> None:
            self.image = image

        def prepareForExport(self, **kwargs: object) -> object:  # noqa: N802
            calls.append(("prepare", self.image, kwargs))
            return "prepared-image"

        def toGeoTIFF(self, file: str, **kwargs: object) -> None:  # noqa: N802
            calls.append(("download", self.image, kwargs))
            with rio.open(
                file,
                "w",
                driver="GTiff",
                height=1,
                width=1,
                count=1,
                dtype="float32",
                crs="EPSG:4326",
                transform=from_origin(0, 1, 1, 1),
            ) as dst:
                dst.write(np.array([[7.0]], dtype="float32"), 1)

    monkeypatch.setattr(base, "ImageAccessor", FakeImageAccessor)
    download_kwargs = {
        "dtype": "float32",
        "crs": "EPSG:4326",
        "scale": 30,
        "resampling": "near",
        "max_tile_size": 8,
    }
    output_path = tmp_path / "download.tif"

    base.download_ee_image(
        cast("ee.Image", "image"),
        cast("ee.Geometry", "bounds"),
        output_path,
        download_kwargs,
    )

    assert calls == [
        (
            "prepare",
            "image",
            {
                "dtype": "float32",
                "crs": "EPSG:4326",
                "scale": 30,
                "resampling": "near",
                "region": "bounds",
            },
        ),
        (
            "download",
            "prepared-image",
            {
                "overwrite": True,
                "max_tile_size": 8,
            },
        ),
    ]
    assert download_kwargs["max_tile_size"] == 8
    with rio.open(output_path) as src:
        assert src.count == 1
        assert src.compression.value == "LZW"
        assert src.read(1).tolist() == [[7.0]]
