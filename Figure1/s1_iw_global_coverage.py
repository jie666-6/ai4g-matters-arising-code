"""
Global Sentinel-1 IW GRD acquisition frequency, per year (2014-2024).

Step 1 (download): for every day in the period, query the Google Earth Engine
collection COPERNICUS/S1_GRD, keep only scenes with instrumentMode == 'IW',
and export the scene footprints of that day to one KML file
(Sentinel1_Footprints_YYYY-MM-DD.kml).

Step 2 (rasterize): for every year, burn each scene footprint into a global
0.1 degree grid (EPSG:4326, 1800 x 3600) and sum, giving the number of
IW GRD scenes covering each grid cell in that year
(Global_coverage_frequency_YYYY.tif, float32, 0 = no coverage / nodata).

Notes
- A cell is counted when its centre falls inside a footprint
  (rasterio.features.rasterize default, all_touched=False).
- The value is a count of GRD scenes. Consecutive GRD slices of the same
  orbit overlap slightly, so cells in these overlaps are counted once per slice.
- All polarisation combinations (SDV, SDH, SSV, SSH) are included.

Requirements: earthengine-api, geemap, geopandas, rasterio, numpy
Earth Engine access: run `earthengine authenticate` once, and provide your own
Google Cloud project registered for Earth Engine via --ee-project or the
EE_PROJECT environment variable.

Usage
    # download footprints and build yearly maps
    python s1_iw_global_coverage.py --ee-project YOUR_GEE_PROJECT \
        --kml-dir ./S1_IW_footprints --out-dir ./S1_IW_coverage_yearly

    # only build yearly maps from KML files that are already downloaded
    python s1_iw_global_coverage.py --skip-download \
        --kml-dir ./S1_IW_footprints --out-dir ./S1_IW_coverage_yearly
"""

import argparse
import gc
import glob
import os
import time
from datetime import datetime, timedelta
from multiprocessing import Pool

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import rasterize

try:  # enable the KML drivers when geopandas reads through fiona
    import fiona
    fiona.drvsupport.supported_drivers['LIBKML'] = 'rw'
    fiona.drvsupport.supported_drivers['KML'] = 'rw'
except Exception:
    pass

# Global 0.1 degree grid
OUT_SHAPE = (1800, 3600)
TRANSFORM = rasterio.transform.from_bounds(-180, -90, 180, 90, OUT_SHAPE[1], OUT_SHAPE[0])


# ---------------------------------------------------------------------------
# Step 1: daily footprint download from Google Earth Engine
# ---------------------------------------------------------------------------
def export_daily_footprints(ee, geemap, output_folder, date):
    start_date_str = date.strftime('%Y-%m-%d')
    end_date_str = (date + timedelta(days=1)).strftime('%Y-%m-%d')

    filename_out = os.path.join(output_folder, f'Sentinel1_Footprints_{start_date_str}.kml')
    if os.path.exists(filename_out):
        return

    s1_iw = ee.ImageCollection('COPERNICUS/S1_GRD') \
        .filterDate(start_date_str, end_date_str) \
        .filter(ee.Filter.eq('instrumentMode', 'IW')) \
        .filterBounds(ee.Geometry.Rectangle([-180, -90, 180, 90]))

    if s1_iw.size().getInfo() == 0:
        print(f'No Sentinel-1 IW images on {start_date_str}')
        return

    footprints = s1_iw.map(lambda image: ee.Feature(image.geometry(), {'ID': image.id()}))
    geemap.ee_export_vector(ee.FeatureCollection(footprints), filename=filename_out)


def kml_download(output_folder, start_date, end_date, ee_project):
    import ee
    import geemap

    if not ee_project:
        raise SystemExit('Please provide a Google Earth Engine project via '
                         '--ee-project or the EE_PROJECT environment variable.')
    ee.Initialize(project=ee_project)

    current_date = start_date
    while current_date < end_date:
        export_daily_footprints(ee, geemap, output_folder, current_date)
        current_date += timedelta(days=1)


# ---------------------------------------------------------------------------
# Step 2: yearly coverage frequency maps
# ---------------------------------------------------------------------------
def process_kml(kml_file):
    gdf = gpd.read_file(kml_file)
    mask = np.zeros(OUT_SHAPE, dtype=np.float32)
    for geom in gdf.geometry:
        mask += rasterize([(geom, 1)], out_shape=OUT_SHAPE, transform=TRANSFORM)
    print(f'Calculation done for {kml_file}')
    return mask


def yearly_frequency_maps(kml_folder, output_folder, years, max_workers=6):
    meta = {
        'driver': 'GTiff',
        'count': 1,
        'dtype': 'float32',
        'nodata': 0,
        'width': OUT_SHAPE[1],
        'height': OUT_SHAPE[0],
        'crs': 'EPSG:4326',
        'transform': TRANSFORM,
    }

    for yyyy in years:
        final_map = os.path.join(output_folder, f'Global_coverage_frequency_{yyyy}.tif')
        if os.path.exists(final_map):
            continue

        files = sorted(glob.glob(os.path.join(kml_folder, f'Sentinel1_Footprints_{yyyy}-*.kml')))
        if not files:
            print(f'No KML files found for {yyyy}, skipped')
            continue

        coverage_frequency = np.zeros(OUT_SHAPE, dtype=np.float32)
        time_s = time.time()
        with Pool(processes=max_workers) as pool:
            for result in pool.imap_unordered(process_kml, files):
                coverage_frequency += result
                del result
                gc.collect()
        print(f'{yyyy}: {len(files)} files processed in {time.time() - time_s:.0f} s '
              f'using {max_workers} workers')

        with rasterio.open(final_map, 'w', **meta) as dst:
            dst.write(coverage_frequency, 1)

    print('Done')


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--kml-dir', default='./S1_IW_footprints',
                        help='folder for the daily footprint KML files')
    parser.add_argument('--out-dir', default='./S1_IW_coverage_yearly',
                        help='folder for the yearly frequency GeoTIFFs')
    parser.add_argument('--start-year', type=int, default=2014)
    parser.add_argument('--end-year', type=int, default=2024, help='inclusive')
    parser.add_argument('--ee-project', default=os.environ.get('EE_PROJECT'),
                        help='Google Earth Engine cloud project ID '
                             '(default: EE_PROJECT environment variable)')
    parser.add_argument('--workers', type=int, default=6)
    parser.add_argument('--skip-download', action='store_true',
                        help='only build the yearly maps from existing KML files')
    args = parser.parse_args()

    os.makedirs(args.kml_dir, exist_ok=True)
    os.makedirs(args.out_dir, exist_ok=True)

    if not args.skip_download:
        kml_download(args.kml_dir,
                     datetime(args.start_year, 1, 1),
                     datetime(args.end_year + 1, 1, 1),
                     args.ee_project)

    yearly_frequency_maps(args.kml_dir, args.out_dir,
                          range(args.start_year, args.end_year + 1),
                          max_workers=args.workers)


if __name__ == '__main__':
    main()
