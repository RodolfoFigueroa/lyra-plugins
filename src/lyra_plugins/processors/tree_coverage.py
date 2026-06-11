import ee
from lyra.utils.ee import reduce_ee_image_over_gdf_factory


def load_tree_coverage_img(bbox: ee.Geometry) -> ee.Image:
    return (
        ee.ImageCollection(
            "projects/sat-io/open-datasets/facebook/meta-canopy-height",
        )
        .filterBounds(bbox)
        .mean()
        .gte(ee.Number(3))
        .multiply(ee.image.Image.pixelArea())
    )


METRIC_DESCRIPTION: str = (
    "Computes tree canopy coverage area in square metres for each spatial unit."
)

TAVI_HINT = (
    "Use this tool when the user asks about greenery, vegetation, "
    "tree cover, canopy, or urban forests. Returns the percentage of land area "
    "covered by tree canopy for each census tract, derived from high-resolution "
    "aerial imagery."
)

calculate = reduce_ee_image_over_gdf_factory(
    load_tree_coverage_img,
    reducer=ee.Reducer.sum(),
    scale=25,
)
