"""Vectorize AI4G flood-detection point data into a GeoPackage.

The AI4G dataset provides flood detections as point locations (lon/lat). This
script converts each point into a small square polygon (roughly one AI4G pixel,
~20 m at the equator) and writes them as a GeoPackage layer, so the detections
can be inspected and compared against other flood extents in a GIS.

Dependencies: pandas, geopandas, shapely, pyarrow
"""

import argparse
from pathlib import Path
import geopandas as gpd
import pandas as pd
from shapely.geometry import Point, Polygon


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


def parquet2geopackage(ai4g_df: pd.DataFrame, out_fpath: Path):
    """Convert AI4G flood points into square polygons and write a GeoPackage.

    Each detection point is converted into a square polygon that approximates
    one AI4G pixel (~20 m at the equator, converted to degrees) centred on the
    point. The result is written to a single 'ai4g_flood' layer in a GeoPackage.

    Parameters
    ----------
    ai4g_df : pd.DataFrame
        AI4G flood detections containing ``lon`` and ``lat`` columns.
    out_fpath : Path
        Path of the output GeoPackage (``.gpkg``) to write.
    """
    # Define the pixel size in degrees (20 meters converted to degrees)
    pixel_size = 20 / 111320

    # Vectorize flood point detections
    polygons = []
    for idx, row in ai4g_df.iterrows():
        center = Point(row['lon'], row['lat'])
        minx = center.x - pixel_size / 2
        maxx = center.x + pixel_size / 2
        miny = center.y - pixel_size / 2
        maxy = center.y + pixel_size / 2
        polygon = Polygon([(minx, miny), (minx, maxy), (maxx, maxy), (maxx, miny), (minx, miny)])
        polygons.append(polygon)
    gdf = gpd.GeoDataFrame(ai4g_df, geometry=polygons, crs="EPSG:4326")

    # write DataFrame to file
    gdf.to_file(out_fpath, layer='ai4g_flood', driver="GPKG")


def main():
    ap = argparse.ArgumentParser(
        description="Vectorize AI4G flood detections into a GeoPackage.")
    ap.add_argument("--parquet", required=True,
                    help="AI4G parquet file, e.g. N03E042-post-processing.parquet")
    ap.add_argument("--out", required=True, help="Output GeoPackage (.gpkg) path")
    args = ap.parse_args()

    ai4g_df = read_ai4g_flood_data(Path(args.parquet))
    ai4g_df = filter_ai4g_flood_data(ai4g_df)
    parquet2geopackage(ai4g_df, out_fpath=Path(args.out))

    print(f"{len(ai4g_df)} detections"
          + ("" if args.raw else " after README filter"))
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
