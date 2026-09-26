from typing import Literal, get_args

import ee

AllowedGhslYearsT = Literal[
    1975, 1980, 1985, 1990, 1995, 2000, 2005, 2010, 2015, 2020, 2025
]
AVAILABLE_GHSL_YEARS = get_args(AllowedGhslYearsT)
GHSL_BUILT_SURFACE_COLLECTION = "JRC/GHSL/P2023A/GHS_BUILT_S"
GHSL_ANALYSIS_SCALE_M = 100
GHSL_BUILT_SURFACE_BAND = "built_surface"


def load_urbanized_area_img(year: AllowedGhslYearsT) -> ee.Image:
    return ee.Image(f"{GHSL_BUILT_SURFACE_COLLECTION}/{year}").select(
        GHSL_BUILT_SURFACE_BAND
    )
