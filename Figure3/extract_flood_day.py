"""
Extract the AI4G flood detections of a single acquisition day from an
ai4g-flood-dataset tile (*-post-processing.parquet) and rasterise them,
without any spatial buffer, to a GeoTIFF.

Each detection point is burned into exactly one pixel. No buffer or dilation
is applied, because the public AI4G data release does not provide buffered
single-day (event-level) flood maps.

Usage (from the folder containing the parquet file):
    python extract_flood_day.py \
        --parquet N48E006-post-processing.parquet \
        --tile N48E006 \
        --date 2021-07-15 \
        --out N48E006_2021-07-15_raw.tif

Add --filtered to apply the post-processing filter recommended in the AI4G
dataset README.

Dependencies: pandas, numpy, rasterio, pyarrow
    pip install pandas numpy rasterio pyarrow
"""

import argparse
import re

import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import from_origin

# Pixel size given in the AI4G dataset README (~20 m at the equator).
RESOLUTION_DEG = 0.00018
TILE_SIZE_DEG = 3  # AI4G tiles are 3 deg x 3 deg

FLOOD_VALUE = 2  # same code as "flood" in the AI4G rasters (1 = exclusion layer, not produced here)


def parse_tile_bounds(tile_id: str):
    """Convert a tile ID such as 'N48E006' or 'S12W045' (south-west corner)
    to (lon_min, lat_min, lon_max, lat_max)."""
    m = re.fullmatch(r"([NS])(\d+)([EW])(\d+)", tile_id.upper())
    if not m:
        raise ValueError(f"Cannot parse tile ID '{tile_id}', expected e.g. N48E006")
    ns, lat_str, ew, lon_str = m.groups()
    lat_min = int(lat_str) * (1 if ns == "N" else -1)
    lon_min = int(lon_str) * (1 if ew == "E" else -1)
    return lon_min, lat_min, lon_min + TILE_SIZE_DEG, lat_min + TILE_SIZE_DEG


def apply_readme_filter(df: pd.DataFrame) -> pd.DataFrame:
    """Post-processing filter recommended in the AI4G dataset README."""
    return df[
        (df.dem_metric_2 < 10)
        & (df.soil_moisture_sca > 1)
        & (df.soil_moisture_zscore > 1)
        & (df.soil_moisture > 20)
        & (df.temp > 0)
        & (df.land_cover != 60)
        & (df.edge_false_positives == 0)
    ]


def points_to_geotiff(points_df, lon_min, lat_min, lon_max, lat_max, resolution, out_path):
    """Burn (lat, lon) detection points into a uint8 grid covering the whole tile.
    Output values: 2 = flood detection, 0 = no detection (nodata)."""
    width = int(round((lon_max - lon_min) / resolution))
    height = int(round((lat_max - lat_min) / resolution))
    grid = np.zeros((height, width), dtype=np.uint8)

    lats = points_df["lat"].to_numpy()
    lons = points_df["lon"].to_numpy()
    inside = (lons >= lon_min) & (lons < lon_max) & (lats >= lat_min) & (lats < lat_max)
    rows = ((lat_max - lats[inside]) / resolution).astype(int)
    cols = ((lons[inside] - lon_min) / resolution).astype(int)
    grid[rows, cols] = FLOOD_VALUE

    profile = {
        "driver": "GTiff",
        "height": height,
        "width": width,
        "count": 1,
        "dtype": "uint8",
        "crs": "EPSG:4326",
        "transform": from_origin(lon_min, lat_max, resolution, resolution),
        "nodata": 0,
        "compress": "lzw",
    }
    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(grid, 1)
    return int((grid == FLOOD_VALUE).sum())


def main():
    ap = argparse.ArgumentParser(description="Rasterise single-day AI4G flood detections (no buffer).")
    ap.add_argument("--parquet", required=True, help="AI4G tile file, e.g. N48E006-post-processing.parquet")
    ap.add_argument("--tile", required=True, help="Tile ID, e.g. N48E006")
    ap.add_argument("--date", required=True, help="Acquisition date, YYYY-MM-DD")
    ap.add_argument("--out", required=True, help="Output GeoTIFF path")
    ap.add_argument("--filtered", action="store_true",
                    help="Apply the post-processing filter recommended in the AI4G README")
    args = ap.parse_args()

    df = pd.read_parquet(args.parquet)
    y, m, d = map(int, args.date.split("-"))
    day_df = df[(df.year == y) & (df.month == m) & (df.day == d)]
    n_raw = len(day_df)
    if args.filtered:
        day_df = apply_readme_filter(day_df)

    print(f"{args.tile} {args.date}: {n_raw} raw detections"
          + (f", {len(day_df)} after README filter" if args.filtered else ""))
    if len(day_df) == 0:
        print("Warning: no detections for this date; writing an empty raster.")

    n_pix = points_to_geotiff(day_df, *parse_tile_bounds(args.tile), RESOLUTION_DEG, args.out)
    print(f"Wrote {args.out} ({n_pix} flood pixels)")


if __name__ == "__main__":
    main()
