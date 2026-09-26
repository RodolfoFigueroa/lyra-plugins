# Lyra geospatial indicators

This package adapts the calculations in `src/lyra_plugins/metrics` into four
Lyra table metrics. The factory is `lyra_plugins.definitions:create_plugin`.
`lyra.plugin.json` is generated from that factory and included in the existing
Hatch wheel and source archive configuration.

| Metric | Required parameters | Output column | Unit | Reduction resolution |
| --- | --- | --- | --- | --- |
| `temperature` | `year`, `season` | `temperature_c` | degrees Celsius (`degC`) | 30 m |
| `tree_coverage` | `min_tree_height` | `tree_coverage_m2` | m² (`m2`) | 1 m |
| `urbanized_area` | `year` | `urbanized_area_m2` | m² (`m2`) | 100 m |
| `urbanization_year` | none | `urbanization_year` | calendar year (`calendar_year`) | 100 m |

All output columns are nullable. Each result has exactly one row per location
feature, in input order. The adapters match returned rows using the original
feature IDs and reject missing, extra, or duplicate IDs. Null reductions remain
null; they are never replaced with zero. Existing calculation errors propagate.
Urbanization years are returned as integers or null, without rounding.

## Inputs and calculations

All metrics take a Lyra `location` containing Polygon/MultiPolygon features with
unique string IDs and a declared CRS. No additional feature properties or
`bounds` argument are required. The adapters preserve CRS and properties when
converting inputs to GeoDataFrames. Existing workflow and utility code performs
reprojection to EPSG:4326 for Earth Engine.

- **Temperature:** `year` is 2022, 2023, 2024, or 2025; `season` is `spring`,
  `summer`, `autumn`, or `winter`. These follow the existing date utility:
  March–May, June–August, September–November, and December–February respectively.
  Winter begins in December of the preceding year. The date utility returns
  the season's first and last calendar days; Earth Engine's
  [exclusive end date](https://developers.google.com/earth-engine/apidocs/ee-imagecollection-filterdate)
  excludes that last day. This existing behavior is preserved. The workflow
  masks dilated-cloud, cloud, and cloud-shadow QA bits, averages `ST_B10`
  over time, applies `ST_B10 * 0.00341802 + 149 - 273.15`, and takes a spatial
  mean at 30 m reduction resolution. This measures land-surface
  temperature, not air temperature. An empty image collection raises the
  existing `ValueError`; missing polygon reductions remain null.
- **Tree coverage:** `min_tree_height` is a required integer threshold in metres;
  height equal to the threshold qualifies. No new default or range restriction
  is introduced. The workflow takes the pixelwise maximum across intersecting
  canopy images, uses the first image's projection, and applies no date filter.
  After thresholding, `unmask(0)` makes masked source pixels contribute zero
  area, so zero does not establish an observed absence of trees. The threshold
  image is multiplied by pixel area and summed at 1 m reduction resolution.
  Any null returned by the reduction remains null at the adapter boundary.
- **Urbanized area:** `year` is a GHSL epoch from 1975 through 2025 in five-year
  increments. The calculation sums the `built_surface` band in square metres.
- **Urbanization year:** no ordinary parameters. The calculation returns the
  earliest supported GHSL epoch in which built-up surface reaches at least 20%
  of the polygon's area, or null if no epoch qualifies. This is an epoch estimate,
  not a precise date of urban development. A result of 1975 may reflect earlier
  development. The threshold uses Earth Engine polygon area with `maxError=1`
  metre.

The calculations have no parameter defaults. Extra parameter fields are rejected.
For `urbanization_year`, omit `input.parameters` entirely.

## Data and runtime requirements

The normal Lyra worker initializes Earth Engine using deployment configuration.
The plugin does not authenticate, initialize Earth Engine, or discover
credentials. Imports, factory construction, and manifest generation do not
construct Earth Engine images or access remote data. Standalone live execution
needs a separately initialized Earth Engine environment with asset access.

The unchanged data sources are:

- [Landsat 9 Collection 2 Tier 1 Level 2](https://developers.google.com/earth-engine/datasets/catalog/LANDSAT_LC09_C02_T1_L2),
  `LANDSAT/LC09/C02/T1_L2`, using `ST_B10`. Cloud masking and missing temperature
  data can limit usable observations.
- [Meta/WRI canopy height maps](https://sustainability.atmeta.com/blog/2024/04/22/using-artificial-intelligence-to-map-the-earths-forests/),
  accessed through the [community Earth Engine collection](https://gee-community-catalog.org/projects/meta_trees/)
  `projects/sat-io/open-datasets/facebook/meta-canopy-height`. The source imagery
  spans 2009–2020, predominantly 2018–2020: the result is a canopy baseline
  assembled from imagery of different dates. Access to and availability of this
  exact collection must be verified in the deployment.
- [GHSL built-up surface P2023A](https://developers.google.com/earth-engine/datasets/catalog/JRC_GHSL_P2023A_GHS_BUILT_S),
  `JRC/GHSL/P2023A/GHS_BUILT_S`. Its epochs include spatial and temporal
  interpolation/extrapolation. The workflows use only 1975–2025 even though the
  source catalog also provides 2030.

## Example request

Submit this metric input through the Lyra job API. The explicit polygon is an
example location in Mexico City; live data availability has not been tested.

```json
{
  "metric": "tree_coverage",
  "input": {
    "parameters": {"min_tree_height": 3},
    "location": {
      "data_type": "geojson",
      "value": {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
        "features": [{
          "type": "Feature",
          "id": "cdmx-example",
          "properties": {},
          "geometry": {
            "type": "Polygon",
            "coordinates": [[
              [-99.19, 19.42], [-99.18, 19.42], [-99.18, 19.43],
              [-99.19, 19.43], [-99.19, 19.42]
            ]]
          }
        }]
      }
    }
  }
}
```

## Local installation and validation

Use Python 3.11 or later, as declared by the project, and the existing `uv.lock`.
`uv sync` installs the project and its declared dependencies in the development
environment. The Lyra SDK and utilities use the Git sources in `pyproject.toml`.
Columns use SDK `Unit` members, including `CALENDAR_YEAR` for the urbanization
epoch.

```sh
uv sync
uv run lyra-plugin build-manifest
uv run lyra-plugin describe
uv run lyra-plugin check-manifest
uv run ruff format .
uv run ruff check .
uv run ty check
uv run pytest --cov=lyra_plugins --cov-report=term-missing --cov-report=xml
```

Regenerate the manifest after changing a metric contract; never edit it manually.
The full test command writes `coverage.xml`. Offline tests compare adapters with
the original callables using mocked Earth Engine boundaries, distinct values,
nonlexical feature IDs, shuffled results, nulls, and projected polygon and
multipolygon inputs. They also exercise SDK parameter preparation, result
normalization, error propagation, and imports without Earth Engine initialization.
These tests validate the integration contract, not scientific correctness or
real Earth Engine results. Deployment, asset access, and live computation require
separate validation; no production jobs are run during authoring.
