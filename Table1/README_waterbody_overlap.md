# AI4G waterbody overlap

This workflow measures how much AI4G flood detection overlaps permanent and seasonal water from GFM and GSWE within individual waterbody polygons. The waterbody polygons and their types are based on OpenStreetMap (OSM) data.

## Requirements

```bash
pip install geopandas rasterio shapely pandas numpy
```

## 1. Prepare reference rasters

Edit the country paths in `01_prepare_reference_water.py`, then run:

```bash
python 01_prepare_reference_water.py
```

The script creates one merged GFM raster and one merged GSWE seasonality raster
for each country. It processes the files in blocks to limit memory use.

GFM classes: `1 = permanent`, `2 = seasonal`.

GSWE seasonality: `12 = permanent`, `1–11 = seasonal`.

## 2. Calculate waterbody statistics

Edit the country paths in `02_waterbody_overlap.py`, then run:

```bash
python 02_waterbody_overlap.py
```

Set the AI4G flood values for each country. Ethiopia uses `(2, 5)` and Kenya
uses `(1,)`.

The script removes fully nested polygons, applies the exact polygon mask and
saves detailed and waterbody-type CSV files. The tables report only permanent
and seasonal overlap from GFM and GSWE.

To process another country, copy one `Country(...)` entry and update its paths
and AI4G flood values.
