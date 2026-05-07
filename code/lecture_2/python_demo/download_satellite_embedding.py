"""
Download Google Earth Engine satellite embedding data for the Mpazi project area.

Collection : GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL
  64 bands (A00-A63), 10 m resolution, float32, annual composites 2017-2024.
  Catalog: https://developers.google.com/earth-engine/datasets/catalog/GOOGLE_SATELLITE_EMBEDDING_V1_ANNUAL

Workflow:
  1. Authenticate / initialize GEE (token cached after first run).
  2. Load project boundary shapefile, reproject to UTM-36S, apply buffer.
  3. Preflight size estimate — try 3 km buffer, then 2 km, then 1 km.
  4. Mosaic collection tiles overlapping the AOI for the target year.
  5. Download as GeoTIFF using ee.data.computePixels() in a 3×3 tile grid,
     then mosaic with GDAL. A single-tile attempt is made first for small AOIs.
  6. Write a readme sidecar alongside the output GeoTIFF.

Output is saved directly to local disk — no Google Drive required.

NOTE: ee.Initialize() requires a registered GEE account. Sign up at
https://earthengine.google.com/signup/ before first run.
"""

import time
from datetime import date
from pathlib import Path

import geopandas as gpd
from tqdm import tqdm

# ---------------------------------------------------------------------------
# Configuration — edit these as needed
# ---------------------------------------------------------------------------

YEARS             = range(2016, 2027)  # years to download; unavailable years are skipped. e.g. =2020 for just one year, OR [2018, 2023] FOR A SPECIFC LIST OF YEARS. Must be within 2017-2024.
BUFFER_KM_OPTIONS = [3, 2, 1]    # AOI buffers tried in order; first that fits is used
SIZE_LIMIT_GB     = 2.0          # abort if estimated uncompressed size exceeds this

COLLECTION    = "GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL"
N_BANDS       = 64               # bands A00-A63
RESOLUTION_M  = 10               # native pixel size in metres
BYTES_PER_PIX = 4                # float32

GEE_PROJECT   = "ee-tannerregan-gwu"   # Google Cloud Project ID with Earth Engine enabled

BOUNDARY_SHP = Path(
    r"C:\Users\tanner_regan\Box\data_main\kigali_rehousing\source"
    r"\mpazi_project_maps\project_boundary.shp"
)
OUTPUT_DIR = Path("C:/Users/tanner_regan/downloads/kigali_downloads/google_satembed")

TILE_GRID_N = 3    # NxN download grid; each tile must be < 48 MB (API limit)
MAX_RETRIES = 3    # per-tile retry attempts


# ---------------------------------------------------------------------------
# GEE authentication
# ---------------------------------------------------------------------------

def authenticate_gee() -> None:
    """
    Initialize the Earth Engine Python API.

    Uses cached credentials on subsequent runs (%APPDATA%/earthengine/credentials).
    On first run, opens a browser for Google OAuth2 login and saves the token.

    earthengine-api >= 0.1.370 requires a Cloud Project ID passed to Initialize().
    Set GEE_PROJECT above if you see a "no project found" error.
    """
    import ee

    NO_PROJECT_MSG = (
        "\n[ERROR] ee.Initialize() requires a Google Cloud Project ID.\n"
        "  1. Find your project ID at https://console.cloud.google.com/\n"
        "  2. Enable the Earth Engine API for that project:\n"
        "     https://console.cloud.google.com/apis/library/earthengine.googleapis.com\n"
        "  3. Set GEE_PROJECT = 'your-project-id' in the config block above.\n"
    )

    kwargs = {"project": GEE_PROJECT} if GEE_PROJECT else {}
    try:
        ee.Initialize(**kwargs)
        print("[GEE] Initialized with cached credentials.")
        return
    except ee.EEException as exc:
        if "no project" in str(exc).lower():
            print(NO_PROJECT_MSG)
            raise SystemExit(1)
        # Any other EEException means credentials are missing — run the auth flow.

    print("[GEE] No cached credentials — launching browser authentication...")
    ee.Authenticate()
    ee.Initialize(**kwargs)
    print("[GEE] Authentication complete.")


# ---------------------------------------------------------------------------
# AOI preflight
# ---------------------------------------------------------------------------

def estimate_size_gb(area_m2: float) -> float:
    """Uncompressed size estimate: pixel count × bands × bytes per pixel."""
    return (area_m2 / RESOLUTION_M ** 2) * N_BANDS * BYTES_PER_PIX / 1e9


def preflight_aoi(boundary_shp: Path, buffer_km_options: list, size_limit_gb: float):
    """
    Load the boundary shapefile, buffer it, and return an ee.Geometry for the
    first buffer size whose estimated download size fits within size_limit_gb.

    Buffering is done in UTM-36S (EPSG:32736, the metric CRS for Kigali) so that
    buffer distances are in metres. The result is converted back to WGS84 for GEE.

    Returns (ee_geom, buffer_km). Raises SystemExit if all options are too large.
    """
    import ee

    print(f"\n[PREFLIGHT] Loading boundary: {boundary_shp}")
    if not boundary_shp.exists():
        raise FileNotFoundError(f"Boundary shapefile not found: {boundary_shp}")

    gdf_utm = gpd.read_file(boundary_shp).to_crs("EPSG:32736")

    for buf_km in buffer_km_options:
        buffered = gdf_utm.buffer(buf_km * 1000)
        area_m2  = buffered.union_all().area
        size_gb  = estimate_size_gb(area_m2)
        print(f"  Buffer {buf_km} km  →  area {area_m2/1e6:.2f} km²  →  est. {size_gb:.3f} GB")

        if size_gb <= size_limit_gb:
            print(f"  [OK] {buf_km} km buffer selected.")
            union_wgs84 = buffered.to_crs("EPSG:4326").union_all()
            ee_geom = ee.Geometry(union_wgs84.__geo_interface__)
            return ee_geom, buf_km

    print(f"\n[ABORT] All buffer options exceeded {size_limit_gb} GB limit.")
    raise SystemExit(1)


# ---------------------------------------------------------------------------
# Image selection
# ---------------------------------------------------------------------------

def select_image(collection: str, year: int, ee_geom):
    """
    Return a mosaicked ee.Image for the given year clipped to ee_geom.

    The collection is tile-based (~163km × 163km per tile), so filterBounds()
    is required to select only tiles that overlap the AOI before mosaicking.
    Without it, .first() would return an arbitrary global tile unrelated to Kigali.
    """
    import ee

    print(f"\n[GEE] Selecting image: {collection}  year={year}")
    ic = (
        ee.ImageCollection(collection)
        .filterDate(f"{year}-01-01", f"{year}-12-31")
        .filterBounds(ee_geom)
    )

    tile_count = ic.size().getInfo()
    print(f"  Tiles found in AOI : {tile_count}")
    if tile_count == 0:
        raise RuntimeError(
            f"No tiles found for {collection} year={year} in the AOI. "
            "Verify the year is within 2017-2024."
        )

    image = ic.mosaic().clip(ee_geom)

    band_names = [b["id"] for b in image.getInfo().get("bands", [])]
    print(f"  Band count : {len(band_names)} (expect {N_BANDS})")
    return image


# ---------------------------------------------------------------------------
# Filename builder
# ---------------------------------------------------------------------------

def build_filename(year: int, buffer_km: int, tile_suffix: str = "") -> str:
    """
    Return a self-describing filename, e.g.:
      GOOGLE_SATELLITE_EMBEDDING_V1_ANNUAL_2020_mpazi_3km.tif
      GOOGLE_SATELLITE_EMBEDDING_V1_ANNUAL_2020_mpazi_3km_tile02.tif
    """
    base = f"GOOGLE_SATELLITE_EMBEDDING_V1_ANNUAL_{year}_mpazi_{buffer_km}km"
    if tile_suffix:
        base += f"_{tile_suffix}"
    return base + ".tif"


# ---------------------------------------------------------------------------
# Download: tiled grid via computePixels
# ---------------------------------------------------------------------------

def make_tile_grid(ee_geom, n: int) -> list:
    """Subdivide the bounding box of ee_geom into n×n ee.Geometry.Rectangle tiles."""
    import ee

    bounds  = ee_geom.bounds().getInfo()["coordinates"][0]
    lons    = [pt[0] for pt in bounds]
    lats    = [pt[1] for pt in bounds]
    lon_min, lon_max = min(lons), max(lons)
    lat_min, lat_max = min(lats), max(lats)
    lon_step = (lon_max - lon_min) / n
    lat_step = (lat_max - lat_min) / n

    return [
        ee.Geometry.Rectangle([
            lon_min + col * lon_step,
            lat_min + row * lat_step,
            lon_min + (col + 1) * lon_step,
            lat_min + (row + 1) * lat_step,
        ])
        for row in range(n)
        for col in range(n)
    ]


def download_tiled(image, ee_geom, year: int, buffer_km: int, out_path: Path) -> bool:
    """
    Download the AOI in a TILE_GRID_N×TILE_GRID_N grid using ee.data.computePixels(),
    then mosaic the tiles into a single GeoTIFF with gdal.Warp.

    ee.data.computePixels() is used (rather than geemap's getDownloadURL) because
    it accepts an explicit UTM grid specification, which guarantees north-up output
    and avoids the per-request pixel-count limit that causes getDownloadURL to return
    empty stubs for large multi-band images.

    The grid is specified in UTM-36S (EPSG:32736) so that pixel dimensions are exact
    metres. computePixels() handles image serialisation internally — the ee.Image
    object is passed directly without pre-encoding.

    Tiles already on disk (>= 10 KB) are skipped, making interrupted downloads resumable.
    """
    import ee
    import ee.data  # submodule must be imported explicitly
    from osgeo import gdal
    from shapely.geometry import box

    MIN_TILE_BYTES   = 10_000    # tiles smaller than this are empty stubs
    MIN_MOSAIC_BYTES = 1_000_000 # mosaic smaller than this indicates a failed download

    tiles_dir = out_path.parent / "_tiles"
    tiles_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n[DOWNLOAD] Tiled download ({TILE_GRID_N}×{TILE_GRID_N} grid)...")
    tile_geoms = make_tile_grid(ee_geom, TILE_GRID_N)
    tile_paths = []

    for i, tile_geom in enumerate(tqdm(tile_geoms, desc="  Tiles", unit="tile")):
        tile_path = tiles_dir / build_filename(year, buffer_km, tile_suffix=f"tile{i:02d}")

        if tile_path.exists() and tile_path.stat().st_size >= MIN_TILE_BYTES:
            print(f"  [SKIP] Tile {i:02d} ({tile_path.stat().st_size/1e6:.1f} MB)")
            tile_paths.append(tile_path.as_posix())
            continue

        # Convert tile bounds to UTM for an accurate metric grid.
        bounds   = tile_geom.bounds().getInfo()["coordinates"][0]
        lons     = [p[0] for p in bounds]
        lats     = [p[1] for p in bounds]
        tile_utm = gpd.GeoDataFrame(
            geometry=[box(min(lons), min(lats), max(lons), max(lats))],
            crs="EPSG:4326",
        ).to_crs("EPSG:32736")
        x_min, y_min, x_max, y_max = tile_utm.total_bounds
        width  = max(1, round((x_max - x_min) / RESOLUTION_M))
        height = max(1, round((y_max - y_min) / RESOLUTION_M))

        for attempt in range(MAX_RETRIES):
            try:
                data = ee.data.computePixels({  # type: ignore[attr-defined]
                    "expression": image,
                    "fileFormat": "GEO_TIFF",
                    "grid": {
                        "dimensions": {"width": width, "height": height},
                        "affineTransform": {
                            "scaleX":     RESOLUTION_M,
                            "shearX":     0,
                            "translateX": x_min,
                            "shearY":     0,
                            "scaleY":     -RESOLUTION_M,  # negative = north-up
                            "translateY": y_max,
                        },
                        "crsCode": "EPSG:32736",
                    },
                })
                tile_path.write_bytes(data)

                if tile_path.stat().st_size >= MIN_TILE_BYTES:
                    print(f"  Tile {i:02d}: {tile_path.stat().st_size/1e6:.1f} MB  ({width}×{height} px)")
                    tile_paths.append(tile_path.as_posix())
                    break
                print(f"  [WARNING] Tile {i:02d} attempt {attempt+1}: result too small.")
            except Exception as exc:
                wait = 2 ** attempt
                print(f"  [WARNING] Tile {i:02d} attempt {attempt+1}: {exc} — retrying in {wait}s")
                time.sleep(wait)
        else:
            print(f"  [WARNING] Tile {i:02d} failed after {MAX_RETRIES} attempts — skipping.")

    if not tile_paths:
        print("  [FAIL] No tiles downloaded successfully.")
        return False

    print(f"\n[MOSAIC] Merging {len(tile_paths)}/{len(tile_geoms)} tiles...")
    gdal.Warp(
        out_path.as_posix(),
        tile_paths,
        format="GTiff",
        creationOptions=["COMPRESS=LZW", "TILED=YES"],
    )

    if out_path.exists() and out_path.stat().st_size >= MIN_MOSAIC_BYTES:
        print(f"  [OK] {out_path.name}  ({out_path.stat().st_size/1e6:.1f} MB)")
        return True

    actual = out_path.stat().st_size if out_path.exists() else 0
    print(f"  [FAIL] Output too small ({actual} bytes).")
    return False


# ---------------------------------------------------------------------------
# Readme sidecar
# ---------------------------------------------------------------------------

def write_readme(out_path: Path, date_start: str, date_end: str, buffer_km: int, tiled: bool) -> None:
    """Write a provenance sidecar text file alongside the GeoTIFF."""
    readme = out_path.with_name(out_path.stem + "_readme.txt")
    content = (
        f"Source collection : {COLLECTION}\n"
        f"GEE catalog URL   : https://developers.google.com/earth-engine/datasets/catalog/"
        f"GOOGLE_SATELLITE_EMBEDDING_V1_ANNUAL\n"
        f"Download date     : {date.today().isoformat()}\n"
        f"Date filter       : {date_start} to {date_end}\n"
        f"Buffer applied    : {buffer_km} km around Mpazi project boundary\n"
        f"Band count        : {N_BANDS} (A00-A63; float32 embedding vectors)\n"
        f"Native resolution : {RESOLUTION_M} m\n"
        f"CRS (as exported) : EPSG:32736 (UTM Zone 36S)\n"
        f"Tiled download    : {'yes — patches merged with gdal.Warp' if tiled else 'no'}\n"
        f"Output file       : {out_path.name}\n"
        f"Boundary shapefile: {BOUNDARY_SHP}\n"
        f"\n"
        f"About the dataset:\n"
        f"  Google Satellite Embedding V1 Annual is a 64-dimensional embedding derived\n"
        f"  from Sentinel-1, Sentinel-2, Landsat 8/9, GEDI, GLO-30 DEM, ERA5-Land,\n"
        f"  ALOS PALSAR-2, GRACE, and text data. All 64 bands form a unit-length vector\n"
        f"  and must be used together; individual bands are not independently meaningful.\n"
        f"  Producer: Google / Google DeepMind.  Temporal coverage: 2017-2024.\n"
    )
    readme.write_text(content, encoding="utf-8")
    print(f"  Readme written: {readme.name}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 65)
    print("Google Satellite Embedding Downloader")
    print(f"  Collection : {COLLECTION}")
    print(f"  Years      : {min(YEARS)}–{max(YEARS)}")
    print(f"  Output     : {OUTPUT_DIR}")
    print("=" * 65)

    authenticate_gee()
    ee_geom, buffer_km = preflight_aoi(BOUNDARY_SHP, BUFFER_KM_OPTIONS, SIZE_LIMIT_GB)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    skipped, failed, completed = [], [], []

    for year in YEARS:
        print(f"\n{'─' * 65}")
        print(f"  Year {year}")
        print(f"{'─' * 65}")

        out_path = OUTPUT_DIR / build_filename(year, buffer_km)
        if out_path.exists() and out_path.stat().st_size > 0:
            print(f"[SKIP] Output already exists: {out_path.name}")
            skipped.append(year)
            continue

        try:
            image = select_image(COLLECTION, year, ee_geom)
        except RuntimeError as exc:
            print(f"[SKIP] {exc}")
            skipped.append(year)
            continue

        success = download_tiled(image, ee_geom, year, buffer_km, out_path)

        if not success:
            print(f"[FAIL] Year {year} — check GEE access, GEE_PROJECT, or try a smaller buffer.")
            failed.append(year)
            continue

        write_readme(out_path, f"{year}-01-01", f"{year}-12-31", buffer_km, tiled=True)
        completed.append(year)

    print("\n" + "=" * 65)
    print("Summary")
    print(f"  Downloaded : {completed  or 'none'}")
    print(f"  Skipped    : {skipped    or 'none'}")
    print(f"  Failed     : {failed     or 'none'}")
    print("=" * 65)

    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
