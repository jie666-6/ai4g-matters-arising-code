"""Rasterize AI4G flood-detection point data onto the GFM grid.

The AI4G dataset provides flood detections as point locations (lon/lat). This
script converts those points into a raster and reprojects them onto the same
grid and coordinate reference system (CRS) as the corresponding reference raster.
The resulting layers therefore share a common grid, which makes it straightforward
to compare the AI4G and GFM flood extents for reference flood events.

Dependencies: pandas, geopandas, shapely, rasterio, pyarrow
"""

import argparse
from datetime import date
from pathlib import Path
import geopandas as gpd
import pandas as pd
import rasterio
from rasterio.features import rasterize
from shapely.geometry import Point


def read_ai4g_flood_data(ai4g_parq_path: Path) -> pd.DataFrame:
    """Load AI4G flood points from a local parquet file.

    Parameters
    ----------
    ai4g_parq_path : Path
        Path to the parquet file containing the AI4G flood detections.

    Returns
    -------
    pd.DataFrame
        DataFrame with the raw AI4G flood detections.
    """
    return pd.read_parquet(ai4g_parq_path)


def filter_ai4g_flood_data(ai4g_df: pd.DataFrame) -> pd.DataFrame:
    """Remove likely false positives from the AI4G flood detections.

    The filtering criteria follow the description of the AI4G dataset on
    HuggingFace to eliminate detections that are unlikely to correspond to
    actual flood water. Only rows that satisfy all of the following conditions
    are kept:

        - DEM metric 2 (slope) is below 10.
        - Soil moisture surface area and soil moisture z-score are above 1.
        - Absolute soil moisture is above 20.
        - Land surface temperature is above 0.
        - Land cover class is not 60.
        - Edge false positives are equal to 0.

    Parameters
    ----------
    ai4g_df : pd.DataFrame
        AI4G flood detections as returned by :func:`read_ai4g_flood_data`.

    Returns
    -------
    pd.DataFrame
        Filtered DataFrame containing only the likely true flood detections.
    """
    ai4g_df_filtered = ai4g_df[
        (ai4g_df.dem_metric_2 < 10) &
        (ai4g_df.soil_moisture_sca > 1) &
        (ai4g_df.soil_moisture_zscore > 1) &
        (ai4g_df.soil_moisture > 20) &
        (ai4g_df.temp > 0) &
        (ai4g_df.land_cover != 60) &
        (ai4g_df.edge_false_positives == 0)
    ]
    return ai4g_df_filtered


def rasterize_and_reproject_ai4g_flood_data(ai4g_df: pd.DataFrame, example_raster_path: Path, out_fpath: Path):
    """Rasterize AI4G points and reproject them to the Equi7Grid used by GFM.

    Point geometries are built from the ``lon`` and ``lat`` columns and created
    in EPSG:4326. They are then reprojected to the CRS of the GFM reference
    raster and rasterized (with ``all_touched=True``) using the reference
    raster's transform, shape and dtype. The result is written as a single-band
    GeoTIFF that can be compared directly against the GFM flood extent.

    Parameters
    ----------
    ai4g_df : pd.DataFrame
        AI4G flood detections containing ``lon`` and ``lat`` columns.
    example_raster_path : Path
        Path to the example raster file used as the reference grid and CRS.
    out_fpath : Path
        Path of the output GeoTIFF to write.
    """
    geometry = [Point(xy) for xy in zip(ai4g_df['lon'], ai4g_df['lat'])]
    gdf = gpd.GeoDataFrame(ai4g_df, geometry=geometry, crs="EPSG:4326")

    with rasterio.open(example_raster_path) as src:
        raster_transform = src.transform
        raster_crs = src.crs
        raster_shape = src.shape
        raster_dtype = src.dtypes[0]

    if gdf.crs != raster_crs:
        gdf = gdf.to_crs(raster_crs)

    # Create a rasterized version of the vector data
    rasterized = rasterize(
        shapes=gdf.geometry.values,
        fill=0,  # Fill value for areas outside the geometries
        out_shape=raster_shape,
        transform=raster_transform,
        all_touched=True,  # This prevents buffer artifacts
        default_value=1,
        dtype=raster_dtype
    )

    with rasterio.open(
            out_fpath,
            'w',
            driver='GTiff',
            height=raster_shape[0],
            width=raster_shape[1],
            count=1,
            dtype=raster_dtype,
            crs=raster_crs,
            transform=raster_transform
    ) as dst:
        dst.write(rasterized, indexes=1)


def main():
    ap = argparse.ArgumentParser(
        description="Rasterize AI4G flood detections onto the GFM grid.")
    ap.add_argument("--parquet", required=True,
                    help="AI4G parquet file, e.g. N48E006-post-processing.parquet")
    ap.add_argument("--example-raster", required=True,
                    help="GFM/reference raster defining the output grid and CRS")
    ap.add_argument("--date", required=True,
                    help="Acquisition date, YYYY-MM-DD")
    ap.add_argument("--filtered", action="store_true",
                    help="Apply the post-processing filter recommended in the "
                         "AI4G dataset README")
    ap.add_argument("--out", required=True, help="Output GeoTIFF path")
    args = ap.parse_args()

    ai4g_df = read_ai4g_flood_data(Path(args.parquet))
    day = date.fromisoformat(args.date)
    ai4g_df = ai4g_df[
        (ai4g_df['year'] == day.year) &
        (ai4g_df['month'] == day.month) &
        (ai4g_df['day'] == day.day)
    ]
    n_raw = len(ai4g_df)
    if args.filtered:
        ai4g_df = filter_ai4g_flood_data(ai4g_df)

    if len(ai4g_df) == 0:
        print("Warning: no detections for this date; writing an empty raster.")

    rasterize_and_reproject_ai4g_flood_data(
        ai4g_df, example_raster_path=Path(args.example_raster),
        out_fpath=Path(args.out))

    print(f"{args.date}: {n_raw} raw detections"
          + (f", {len(ai4g_df)} after README filter" if args.filtered else ""))
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
