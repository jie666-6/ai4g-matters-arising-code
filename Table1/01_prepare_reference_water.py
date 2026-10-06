#!/usr/bin/env python3

from __future__ import annotations

import json
import math
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.windows import Window, bounds as window_bounds, from_bounds


@dataclass(frozen=True)
class Country:
    name: str
    gfm_directory: Path
    gswe_seasonality_directory: Path
    output_directory: Path


# Edit paths here. Add another Country entry to process another country.
COUNTRIES = [
    Country(
        name="ethiopia",
        gfm_directory=Path("/path/to/ethiopia/gfm_water"),
        gswe_seasonality_directory=Path("/path/to/ethiopia/gswe_seasonality"),
        output_directory=Path("/path/to/ethiopia/reference_water"),
    ),
    Country(
        name="kenya",
        gfm_directory=Path("/path/to/kenya/gfm_water"),
        gswe_seasonality_directory=Path("/path/to/kenya/gswe_seasonality"),
        output_directory=Path("/path/to/kenya/reference_water"),
    ),
]

GFM_MONTHLY_PATTERN = "REFERENCE_WATER*.tif"
GSWE_PATTERN = "seasonality_*.tif"

GFM_OUTPUT = "GFM_REFERENCE_WATER_MERGED.tif"
GSWE_OUTPUT = "GSWE_SEASONALITY_MERGED.tif"

NODATA = 255
BLOCK_SIZE = 512
GDAL_CACHEMAX_BYTES = 256_000_000
EXPECTED_MONTHS = 12
STRICT_MONTH_COUNT = True
OVERWRITE = True


def windows(width: int, height: int):
    for row in range(0, height, BLOCK_SIZE):
        for col in range(0, width, BLOCK_SIZE):
            yield Window(
                col,
                row,
                min(BLOCK_SIZE, width - col),
                min(BLOCK_SIZE, height - row),
            )


def remove_output(path: Path) -> None:
    if not path.exists():
        return
    if not OVERWRITE:
        raise FileExistsError(path)
    path.unlink()


def clean_profile(src, width=None, height=None, transform=None):
    return {
        "driver": "GTiff",
        "width": width or src.width,
        "height": height or src.height,
        "count": 1,
        "dtype": "uint8",
        "crs": src.crs,
        "transform": transform or src.transform,
        "nodata": NODATA,
        "compress": "deflate",
        "tiled": True,
        "blockxsize": BLOCK_SIZE,
        "blockysize": BLOCK_SIZE,
        "BIGTIFF": "IF_SAFER",
    }


def same_grid(first, other) -> bool:
    return (
        first.crs == other.crs
        and first.transform.almost_equals(other.transform)
        and first.width == other.width
        and first.height == other.height
    )


def aggregate_gfm(monthly_files: list[Path], output: Path) -> None:
    with rasterio.open(monthly_files[0]) as first:
        profile = clean_profile(first)
        for path in monthly_files[1:]:
            with rasterio.open(path) as src:
                if not same_grid(first, src):
                    raise ValueError(f"GFM grids differ: {path}")

    remove_output(output)
    output.parent.mkdir(parents=True, exist_ok=True)

    with ExitStack() as stack:
        sources = [stack.enter_context(rasterio.open(path)) for path in monthly_files]
        template = sources[0]
        dst = stack.enter_context(rasterio.open(output, "w", **profile))
        for window in windows(template.width, template.height):
            valid_any = np.zeros(
                (int(window.height), int(window.width)), dtype=bool
            )
            permanent = np.zeros_like(valid_any)
            seasonal = np.zeros_like(valid_any)

            for src in sources:
                data = src.read(1, window=window, masked=True)
                values = data.data
                valid = ~np.ma.getmaskarray(data) & (values != NODATA)
                valid_any |= valid
                permanent |= valid & (values == 1)
                seasonal |= valid & (values == 2)

            result = np.full(valid_any.shape, NODATA, dtype="uint8")
            result[valid_any] = 0
            result[seasonal] = 2
            result[permanent] = 1
            dst.write(result, 1, window=window)


def inspect_grid(paths: list[Path]):
    with rasterio.open(paths[0]) as first:
        if first.crs is None:
            raise ValueError(f"Missing CRS: {paths[0]}")
        crs = first.crs
        res_x, res_y = map(abs, first.res)
        origin_x = first.transform.c
        origin_y = first.transform.f
        left, bottom, right, top = first.bounds

    for path in paths[1:]:
        with rasterio.open(path) as src:
            if src.crs != crs or not np.allclose(src.res, (res_x, res_y)):
                raise ValueError(f"CRS or resolution differs: {path}")
            col = (src.transform.c - origin_x) / res_x
            row = (origin_y - src.transform.f) / res_y
            if not (np.isclose(col, round(col)) and np.isclose(row, round(row))):
                raise ValueError(f"Grid is not aligned: {path}")
            left = min(left, src.bounds.left)
            bottom = min(bottom, src.bounds.bottom)
            right = max(right, src.bounds.right)
            top = max(top, src.bounds.top)

    left = origin_x + math.floor((left - origin_x) / res_x) * res_x
    right = origin_x + math.ceil((right - origin_x) / res_x) * res_x
    top = origin_y + math.ceil((top - origin_y) / res_y) * res_y
    bottom = origin_y + math.floor((bottom - origin_y) / res_y) * res_y
    transform = from_origin(left, top, res_x, res_y)
    width = int(round((right - left) / res_x))
    height = int(round((top - bottom) / res_y))
    return crs, transform, width, height


def initialize(dst) -> None:
    for window in windows(dst.width, dst.height):
        data = np.full(
            (int(window.height), int(window.width)), NODATA, dtype="uint8"
        )
        dst.write(data, 1, window=window)


def merge_aligned(paths: list[Path], output: Path, product: str) -> None:
    crs, transform, width, height = inspect_grid(paths)
    with rasterio.open(paths[0]) as first:
        profile = clean_profile(first, width, height, transform)
    profile["crs"] = crs

    remove_output(output)
    output.parent.mkdir(parents=True, exist_ok=True)

    with rasterio.open(output, "w+", **profile) as dst:
        initialize(dst)
        for number, path in enumerate(paths, 1):
            print(f"    {number}/{len(paths)} {path.name}")
            with rasterio.open(path) as src:
                for src_window in windows(src.width, src.height):
                    incoming = src.read(1, window=src_window, masked=True)
                    valid = (
                        ~np.ma.getmaskarray(incoming)
                        & (incoming.data != NODATA)
                    )
                    if not valid.any():
                        continue

                    left, bottom, right, top = window_bounds(
                        src_window, src.transform
                    )
                    raw = from_bounds(left, bottom, right, top, dst.transform)
                    dst_window = Window(
                        int(round(raw.col_off)),
                        int(round(raw.row_off)),
                        int(round(raw.width)),
                        int(round(raw.height)),
                    )
                    current = dst.read(1, window=dst_window)
                    values = incoming.data

                    if product == "gfm":
                        empty = (current == NODATA) & valid
                        current[empty] = values[empty]
                        overlap = (current != NODATA) & valid
                        current[overlap & (values == 2) & (current != 1)] = 2
                        current[overlap & (values == 1)] = 1
                    else:
                        fill = (current == NODATA) & valid
                        current[fill] = values[fill]

                    dst.write(current, 1, window=dst_window)


def prepare_country(country: Country) -> dict:
    if not country.gfm_directory.is_dir():
        raise FileNotFoundError(country.gfm_directory)
    if not country.gswe_seasonality_directory.is_dir():
        raise FileNotFoundError(country.gswe_seasonality_directory)

    country.output_directory.mkdir(parents=True, exist_ok=True)
    aggregated_dir = country.output_directory / "gfm_aggregated_tiles"
    aggregated_dir.mkdir(exist_ok=True)

    aggregated = []
    for tile_dir in sorted(p for p in country.gfm_directory.iterdir() if p.is_dir()):
        monthly = sorted(tile_dir.glob(GFM_MONTHLY_PATTERN))
        if not monthly:
            continue
        if len(monthly) != EXPECTED_MONTHS:
            message = f"{tile_dir.name}: found {len(monthly)} monthly files"
            if STRICT_MONTH_COUNT:
                raise ValueError(message)
            print(f"  Warning: {message}")
        output = aggregated_dir / f"{tile_dir.name}_REFERENCE_WATER_AGG.tif"
        print(f"  Aggregating {tile_dir.name}")
        aggregate_gfm(monthly, output)
        aggregated.append(output)

    if not aggregated:
        raise FileNotFoundError("No GFM monthly tile folders found")

    gfm_output = country.output_directory / GFM_OUTPUT
    print("  Merging GFM")
    merge_aligned(aggregated, gfm_output, "gfm")

    gswe_tiles = sorted(country.gswe_seasonality_directory.glob(GSWE_PATTERN))
    if not gswe_tiles:
        raise FileNotFoundError("No GSWE seasonality tiles found")
    gswe_output = country.output_directory / GSWE_OUTPUT
    print("  Merging GSWE seasonality")
    merge_aligned(gswe_tiles, gswe_output, "gswe")

    return {
        "country": country.name,
        "gfm": str(gfm_output),
        "gswe_seasonality": str(gswe_output),
        "gfm_aggregated_tiles": len(aggregated),
        "gswe_tiles": len(gswe_tiles),
    }


def main() -> None:
    for country in COUNTRIES:
        print(f"\n{country.name.upper()}")
        report = prepare_country(country)
        path = country.output_directory / "reference_water_report.json"
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"  Saved {path}")


if __name__ == "__main__":
    with rasterio.Env(GDAL_CACHEMAX=GDAL_CACHEMAX_BYTES):
        main()
