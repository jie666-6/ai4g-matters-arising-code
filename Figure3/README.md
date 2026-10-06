# Figure 3 – Luxembourg case (July 2021 flood)

`rasterize_ai4g_luxemborg2021.py` rasterizes the AI4G flood detections onto the
same grid and CRS of a reference raster (e.g. GFM data), so the
AI4G can be compared directly to this reference raster.

No buffer is applied: every detection point is burned into one pixel. The public
AI4G release does not provide buffered single-day (event-level) flood maps, so the
figure shows the detections as released.

## Input data

- AI4G flood dataset, tile `N48E006` (`N48E006-post-processing.parquet`),
  downloaded from https://huggingface.co/datasets/ai-for-good-lab/ai4g-flood-dataset, version/commit d89a20673fc91c7cc1a183ade0086b1941ca73ae, accessed 2025-07-28.
- Copernicus EMS Rapid Mapping activation EMSN139 (Luxembourg, July 2021), used as reference.
- GFM flood extent: v3.2, accessed 2025-07-29.

## Requirements

```
pip install pandas numpy rasterio pyarrow geopandas shapely
```

## Commands

Rasterize AI4G detections onto the GFM reference grid for the 2021 Luxemborg flood event (15 July 2021):

```
python rasterize_ai4g_luxemborg2021.py \
    --parquet N48E006-post-processing.parquet \
    --example-raster gfm_flood_extent.tif \
    --date 2021-07-15 \
    --out ai4g_luxemborg2021_raw.tif
```

Detections after the post-processing filter recommended in the AI4G README:

```
python rasterize_ai4g_luxemborg2021.py \
    --parquet N48E006-post-processing.parquet \
    --example-raster gfm_flood_extent.tif \
    --date 2021-07-15 \
    --filtered \
    --out ai4g_luxemborg2021_filtered.tif
```

The output GeoTIFF shares the grid, CRS and dtype of the reference
`--example-raster`; values are `1` where an AI4G detection is burned and `0`
elsewhere.

## Output

- GeoTIFF, EPSG:27704, 20m pixel size.
- Values: `1` = AI4G flood detection, `0` = no detection.
