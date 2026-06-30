import json
from pathlib import Path

from lyra.sdk.models import PluginManifestV3, compile_plugin_manifest


def test_manifest_validates_against_v3_model() -> None:
    raw = json.loads(Path("lyra.plugin.json").read_text(encoding="utf-8"))

    manifest = PluginManifestV3.model_validate(raw)
    compiled = compile_plugin_manifest(manifest)

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

    compiled_by_name = {metric.name: metric for metric in compiled.metrics}
    assert compiled_by_name["accessibility_jobs"].request_schema["required"] == [
        "location",
        "patterns",
    ]
    assert compiled_by_name["accessibility_services"].request_schema["required"] == [
        "location",
        "service_filters",
    ]
    assert compiled_by_name["accessibility_services_with_public_spaces"].request_schema[
        "required"
    ] == ["location", "public_spaces", "service_filters"]
    assert compiled_by_name["temperature"].request_schema["required"] == [
        "location",
        "year",
        "season",
    ]
    assert compiled_by_name["temperature_raster"].request_schema["required"] == [
        "bounds",
        "year",
        "season",
    ]
    assert compiled_by_name["tree_coverage_raster"].request_schema["required"] == [
        "bounds",
    ]
