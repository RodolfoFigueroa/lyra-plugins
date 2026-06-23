import ee


def load_tree_coverage_img(bbox: ee.Geometry) -> ee.Image:
    collection = ee.ImageCollection(
        "projects/sat-io/open-datasets/facebook/meta-canopy-height",
    ).filterBounds(bbox)
    projection = ee.Image(collection.first()).select(0).projection()

    return collection.max().setDefaultProjection(projection).clip(bbox)


def load_tree_coverage_fraction_img(
    bbox: ee.Geometry,
    min_tree_height: float,
) -> ee.Image:
    tree_presence = (
        load_tree_coverage_img(bbox)
        .gte(ee.Number(min_tree_height))
        .unmask(0)
        .clip(bbox)
    )

    return (
        tree_presence.reduceResolution(
            reducer=ee.Reducer.mean(),
            maxPixels=65535,
        )
        .rename("tree_coverage_fraction")
        .clip(bbox)
    )
