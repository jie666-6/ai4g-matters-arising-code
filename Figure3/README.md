# Figure 3 – Luxembourg case (July 2021 flood)

`extract_flood_day.py` extracts the AI4G flood detections of a single Sentinel-1
acquisition day from the public AI4G flood dataset and writes them to a GeoTIFF.

No buffer is applied: every detection point is burned into one pixel. The public
AI4G release does not provide buffered single-day (event-level) flood maps, so the
figure shows the detections as released.

## Input data

- AI4G flood dataset, tile `N48E006` (`N48E006-post-processing.parquet`),
  downloaded from [URL], version/commit [xxx], accessed [date].
- Copernicus EMS Rapid Mapping activation EMSN139 (Luxembourg, July 2021), used as reference.
- GFM flood extent: [product/version, date].

## Requirements

```
pip install pandas numpy rasterio pyarrow
```

## Commands

Run from the folder that contains the parquet file.

Raw detections, 15 July 2021:

```
python extract_flood_day.py --parquet N48E006-post-processing.parquet --tile N48E006 --date 2021-07-15 --out N48E006_2021-07-15_raw.tif
```

Detections after the post-processing filter recommended in the AI4G README:

```
python extract_flood_day.py --parquet N48E006-post-processing.parquet --tile N48E006 --date 2021-07-15 --filtered --out N48E006_2021-07-15_filtered.tif
```

## Output

- GeoTIFF, EPSG:4326, 0.00018° pixel size (as stated in the AI4G README), extent of the 3° x 3° tile.
- Values: `2` = AI4G flood detection, `0` = no detection (nodata).
