# Global Sentinel-1 IW coverage frequency (2014-2024)

`s1_iw_global_coverage.py` reproduces the yearly global maps of Sentinel-1 IW GRD acquisition frequency used in the Matters Arising.

## What it does

1. **Footprint download.** For each day from 2014-01-01 to 2024-12-31, the script queries the Google Earth Engine collection `COPERNICUS/S1_GRD`. It keeps scenes with `instrumentMode == 'IW'` and writes their footprints to `Sentinel1_Footprints_YYYY-MM-DD.kml`.
2. **Yearly frequency maps.** For each year, every footprint is rasterized onto a global 0.1° grid (EPSG:4326, 1800 × 3600) and summed. The result is `Global_coverage_frequency_YYYY.tif`: the number of IW GRD scenes covering each cell in that year. The data type is float32, and 0 marks no coverage (nodata).

## Requirements

```
pip install earthengine-api geemap geopandas rasterio numpy
```

Step 1 needs a Google Earth Engine account and a Google Cloud project registered for Earth Engine (https://developers.google.com/earth-engine/guides/access). Authenticate once with:

```
earthengine authenticate
```

## Usage

```
# Steps 1 and 2
python s1_iw_global_coverage.py --ee-project YOUR_GEE_PROJECT \
    --kml-dir ./S1_IW_footprints --out-dir ./S1_IW_coverage_yearly

# Step 2 only, from KML files that are already downloaded
python s1_iw_global_coverage.py --skip-download \
    --kml-dir ./S1_IW_footprints --out-dir ./S1_IW_coverage_yearly
```

You can also set the project through the `EE_PROJECT` environment variable instead of `--ee-project`. Other options are `--start-year`, `--end-year` (inclusive) and `--workers` (number of parallel processes in step 2). Files that already exist are skipped, so you can resume an interrupted run.

## Notes

- A cell is counted when its centre falls inside a footprint (`rasterio.features.rasterize` with the default `all_touched=False`).
- Values are counts of GRD scenes. Consecutive GRD slices of the same orbit overlap slightly, so cells in these overlaps are counted once per slice.
- All polarisation combinations (SDV, SDH, SSV, SSH) are included.
- The footprints used in the paper were downloaded in February 2025 (2017-2024) and July 2025 (2014-2016). The Earth Engine catalogue can change over time, so a new download may differ slightly.
