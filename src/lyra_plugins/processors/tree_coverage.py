import ee
from lyra.utils.ee import reduce_ee_image_over_gdf_factory

from lyra_plugins.functions.tree_coverage import load_tree_coverage_img

METRIC_DESCRIPTION: str = (
    "Tree canopy coverage fraction, derived from high-resolution aerial imagery."
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
