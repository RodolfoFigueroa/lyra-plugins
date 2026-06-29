import json
from pathlib import Path

from lyra.sdk.models import PluginManifestV2


def test_manifest_validates_against_v2_model() -> None:
    raw = json.loads(Path("lyra.plugin.json").read_text(encoding="utf-8"))

    manifest = PluginManifestV2.model_validate(raw)

    assert {metric.name for metric in manifest.metrics} == {
        "accessibility_jobs",
        "accessibility_services",
        "accessibility_services_with_public_spaces",
        "temperature",
        "temperature_raster",
        "tree_coverage",
        "tree_coverage_raster",
        "urbanized_area",
    }
