#!/usr/bin/env python3

from __future__ import annotations

import json
import math
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import rasterize
from rasterio.vrt import WarpedVRT
from rasterio.warp import Resampling
from rasterio.windows import Window, from_bounds
from shapely.ops import unary_union


@dataclass(frozen=True)
class Country:
    name: str
    boundary: Path
    waterbodies: Path
    ai4g: Path
    gfm: Path
    gswe_seasonality: Path
    output_directory: Path
    flood_values: tuple[int, ...]


# Edit paths here. Add another Country entry to process another country.
COUNTRIES = [
    Country(
        name="ethiopia",
        boundary=Path("/path/to/ethiopia_boundary.geojson"),
        waterbodies=Path("/path/to/ethiopia/waterways.geojson"),
        ai4g=Path("/path/to/ethiopia/ai4g_flood.tif"),
        gfm=Path("/path/to/ethiopia/reference_water/GFM_REFERENCE_WATER_MERGED.tif"),
        gswe_seasonality=Path("/path/to/ethiopia/reference_water/GSWE_SEASONALITY_MERGED.tif"),
        output_directory=Path("/path/to/ethiopia/waterbody_statistics"),
        flood_values=(2, 5),
    ),
    Country(
        name="kenya",
        boundary=Path("/path/to/kenya_boundary.geojson"),
        waterbodies=Path("/path/to/kenya/waterways.geojson"),
        ai4g=Path("/path/to/kenya/kenya-rapid-response.tif"),
        gfm=Path("/path/to/kenya/reference_water/GFM_REFERENCE_WATER_MERGED.tif"),
        gswe_seasonality=Path("/path/to/kenya/reference_water/GSWE_SEASONALITY_MERGED.tif"),
        output_directory=Path("/path/to/kenya/waterbody_statistics"),
        flood_values=(1,),
    ),
]

ANALYSIS_CRS = "EPSG:6933"
ALL_TOUCHED = False
REMOVE_NESTED_POLYGONS = True
CONTAINMENT_TOLERANCE_M2 = 1.0
GDAL_CACHEMAX_BYTES = 256_000_000


def read_vector(path: Path) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(path)
    if gdf.empty or gdf.crs is None:
        raise ValueError(f"Empty vector or missing CRS: {path}")
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    try:
        gdf.geometry = gdf.geometry.make_valid()
    except AttributeError:
        gdf.geometry = gdf.geometry.buffer(0)
    return gdf


def union_geometry(gdf: gpd.GeoDataFrame):
    try:
        return gdf.geometry.union_all()
    except AttributeError:
        return gdf.geometry.unary_union


def remove_nested(gdf: gpd.GeoDataFrame):
    work = gdf.copy()
    work["_source_index"] = work.index.astype(str)
    work["_area"] = work.geometry.area
    work = work.sort_values(
        ["_area", "_source_index"], ascending=[False, True]
    ).reset_index(drop=True)
    index = work.sindex
    kept = set()
    removed = []

    for position, row in work.iterrows():
        candidates = [
            int(i)
            for i in index.query(row.geometry, predicate="intersects")
            if int(i) in kept
        ]
        covered = False
        if candidates:
            cover = unary_union(work.iloc[candidates].geometry.tolist())
            remainder = row.geometry.difference(cover).area
            covered = remainder <= max(
                CONTAINMENT_TOLERANCE_M2, row.geometry.area * 1e-8
            )
        if covered:
            removed.append(
                {
                    "source_index": row["_source_index"],
                    "osm_id": row.get("osm_id", row.get("id", "")),
                    "name": row.get("name", ""),
                    "reason": "fully covered by retained polygon(s)",
                }
            )
        else:
            kept.add(position)

    cleaned = work.iloc[sorted(kept)].drop(
        columns=["_source_index", "_area"]
    ).reset_index(drop=True)
    return cleaned, pd.DataFrame(removed)


def first_value(row, fields, default):
    for field in fields:
        if field in row.index and pd.notna(row[field]):
            value = str(row[field]).strip()
            if value not in {"", "None", "nan"}:
                return value
    return default


def polygon_window(geometry, height, width, transform):
    raw = from_bounds(*geometry.bounds, transform=transform)
    row0 = max(0, math.floor(raw.row_off))
    col0 = max(0, math.floor(raw.col_off))
    row1 = min(height, math.ceil(raw.row_off + raw.height))
    col1 = min(width, math.ceil(raw.col_off + raw.width))
    if row0 >= row1 or col0 >= col1:
        return None
    return Window(col0, row0, col1 - col0, row1 - row0)


def percent(count, total):
    return 100.0 * count / total if total else np.nan


def add_measure(row, name, count, total, pixel_area):
    row[f"{name}_pixels"] = count
    row[f"{name}_km2"] = count * pixel_area / 1e6
    row[f"{name}_pct_of_ai4g"] = percent(count, total)


def process_country(country: Country) -> None:
    inputs = [
        country.boundary,
        country.waterbodies,
        country.ai4g,
        country.gfm,
        country.gswe_seasonality,
    ]
    missing = [str(path) for path in inputs if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing input(s):\n" + "\n".join(missing))

    output = country.output_directory
    output.mkdir(parents=True, exist_ok=True)

    boundary = read_vector(country.boundary).to_crs(ANALYSIS_CRS)
    water = read_vector(country.waterbodies).to_crs(ANALYSIS_CRS)
    water = gpd.clip(water, union_geometry(boundary))
    water = water[
        water.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
        & water.geometry.notna()
        & ~water.geometry.is_empty
    ].copy()

    if REMOVE_NESTED_POLYGONS:
        water, removed = remove_nested(water)
        water.to_file(output / "waterbodies_cleaned.geojson", driver="GeoJSON")
        removed.to_csv(output / "waterbodies_removed.csv", index=False)

    rows = []
    with ExitStack() as stack:
        ai4g_source = stack.enter_context(rasterio.open(country.ai4g))
        ai4g = stack.enter_context(
            WarpedVRT(ai4g_source, crs=ANALYSIS_CRS, resampling=Resampling.nearest)
        )
        grid = {
            "crs": ai4g.crs,
            "transform": ai4g.transform,
            "width": ai4g.width,
            "height": ai4g.height,
            "resampling": Resampling.nearest,
        }

        def aligned(path):
            src = stack.enter_context(rasterio.open(path))
            return stack.enter_context(WarpedVRT(src, **grid))

        gfm = aligned(country.gfm)
        gswe = aligned(country.gswe_seasonality)
        pixel_area = abs(ai4g.transform.a * ai4g.transform.e)

        for number, (source_index, feature) in enumerate(water.iterrows(), 1):
            if number == 1 or number % 250 == 0 or number == len(water):
                print(f"  Polygon {number}/{len(water)}")

            window = polygon_window(
                feature.geometry, ai4g.height, ai4g.width, ai4g.transform
            )
            if window is None:
                continue
            shape = (int(window.height), int(window.width))
            transform = rasterio.windows.transform(window, ai4g.transform)
            polygon = rasterize(
                [(feature.geometry, 1)],
                out_shape=shape,
                transform=transform,
                fill=0,
                dtype="uint8",
                all_touched=ALL_TOUCHED,
            ).astype(bool)
            if not polygon.any():
                continue

            ai4g_data = ai4g.read(1, window=window, masked=True)
            gfm_data = gfm.read(1, window=window, masked=True)
            gswe_data = gswe.read(1, window=window, masked=True)

            ai4g_flood = (
                polygon
                & ~np.ma.getmaskarray(ai4g_data)
                & np.isin(ai4g_data.data, country.flood_values)
            )
            gfm_valid = ~np.ma.getmaskarray(gfm_data)
            gswe_valid = ~np.ma.getmaskarray(gswe_data)

            masks = {
                "gfm_permanent": ai4g_flood & gfm_valid & (gfm_data.data == 1),
                "gfm_seasonal": ai4g_flood & gfm_valid & (gfm_data.data == 2),
                "gswe_permanent": ai4g_flood & gswe_valid & (gswe_data.data == 12),
                "gswe_seasonal": (
                    ai4g_flood
                    & gswe_valid
                    & (gswe_data.data >= 1)
                    & (gswe_data.data <= 11)
                ),
            }

            flood_count = int(ai4g_flood.sum())
            row = {
                "country": country.name,
                "source_index": source_index,
                "osm_id": feature.get("osm_id", feature.get("id", source_index)),
                "name": first_value(
                    feature,
                    ("name", "name_en", "name_latin", "name_am"),
                    "Unnamed",
                ),
                "waterbody_type": first_value(
                    feature,
                    ("water", "natural_class", "waterway"),
                    "water unspecified",
                ),
                "ai4g_flood_pixels": flood_count,
                "ai4g_flood_km2": flood_count * pixel_area / 1e6,
            }
            for name, mask in masks.items():
                add_measure(row, name, int(mask.sum()), flood_count, pixel_area)
            rows.append(row)

    if not rows:
        raise ValueError(f"No polygon statistics produced for {country.name}")
    details = pd.DataFrame(rows).sort_values("ai4g_flood_km2", ascending=False)
    details.to_csv(output / "waterbody_overlap_detailed.csv", index=False)

    sum_columns = [
        column
        for column in details.columns
        if column.endswith("_pixels") or column.endswith("_km2")
    ]
    summary = (
        details.groupby("waterbody_type", dropna=False)
        .agg(
            waterbody_count=("osm_id", "size"),
            **{column: (column, "sum") for column in sum_columns},
        )
        .reset_index()
    )
    denominator = summary["ai4g_flood_pixels"].replace(0, np.nan)
    for source in ("gfm", "gswe"):
        for water_class in ("permanent", "seasonal"):
            name = f"{source}_{water_class}"
            summary[f"{name}_pct_of_ai4g"] = (
                100.0 * summary[f"{name}_pixels"] / denominator
            )

    total = {"waterbody_type": "Total", "waterbody_count": len(details)}
    for column in sum_columns:
        total[column] = details[column].sum()
    for source in ("gfm", "gswe"):
        for water_class in ("permanent", "seasonal"):
            name = f"{source}_{water_class}"
            total[f"{name}_pct_of_ai4g"] = percent(
                total[f"{name}_pixels"], total["ai4g_flood_pixels"]
            )
    summary = pd.concat([summary, pd.DataFrame([total])], ignore_index=True)
    summary.to_csv(output / "waterbody_overlap_by_type.csv", index=False)

    metadata = {
        "country": country.name,
        "flood_values": list(country.flood_values),
        "gfm": {"permanent": 1, "seasonal": 2},
        "gswe_seasonality": {"permanent": 12, "seasonal": "1-11"},
        "analysis_crs": ANALYSIS_CRS,
        "all_touched": ALL_TOUCHED,
        "nested_polygons_removed": REMOVE_NESTED_POLYGONS,
        "polygon_count": len(details),
    }
    (output / "overlap_metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )


def main() -> None:
    for country in COUNTRIES:
        print(f"\n{country.name.upper()}")
        process_country(country)


if __name__ == "__main__":
    with rasterio.Env(GDAL_CACHEMAX=GDAL_CACHEMAX_BYTES):
        main()
