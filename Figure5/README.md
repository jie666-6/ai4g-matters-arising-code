# Figure 5 – Ethiopia case (2024 flood)

`vectorize_ai4g_ethiopia2024.py` converts the AI4G flood detections of the whole 
timeseries (2014-2024) into a GeoPackage of square polygons, so the detections can be
viewed and compared against other flood extents in a GIS.

Each detection point is burned into a small square polygon (roughly one AI4G
pixel, ~20 m at the equator) centred on the point, in EPSG:4326.

## Input data

- AI4G flood dataset, tile `N03E042` (`N03E042-post-processing.parquet`),
  downloaded from https://huggingface.co/datasets/ai-for-good-lab/ai4g-flood-dataset, version/commit d89a20673fc91c7cc1a183ade0086b1941ca73ae, accessed 2025-07-17.

## Requirements

```
pip install pandas geopandas shapely pyarrow
```

## Commands

Collect, filter and convert AI4G flood detections to polygon vector dataset:

```
python vectorize_ai4g_ethiopia2024.py \
    --parquet N03E042-post-processing.parquet \
    --out N03E042_ai4g_flood_filtered.gpkg
```

## Output

- GeoPackage (`.gpkg`), EPSG:4326, with a single `ai4g_flood` layer.
- Each feature is a ~20 m square polygon centred on an AI4G detection point.
