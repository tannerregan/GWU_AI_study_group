"""
Download Google Earth Engine satellite embedding data for the Mpazi project area.

Collection : GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL
  64 bands (A00-A63), 10 m resolution, float32, annual composites 2017-2024.
  Catalog: https://developers.google.com/earth-engine/datasets/catalog/GOOGLE_SATELLITE_EMBEDDING_V1_ANNUAL

Workflow:
  1. Authenticate / initialize GEE (token cached after first run).
  2. Load project boundary shapefile, reproject to UTM-36S, apply buffer.
  3. Preflight size estimate — try 3 km, then 2 km, then 1 km; abort if all exceed SIZE_LIMIT_GB.
  4. Select the annual image for YEAR, clip to AOI.
  5. Download directly to local disk as GeoTIFF via geemap.ee_export_image().
     If the single-tile download fails (GEE pixel-count limit exceeded), fall back to
     a tile-grid approach: download NxN patches then mosaic with GDAL.
  6. Write a readme sidecar file alongside each downloaded GeoTIFF.

NOTE on /content/drive/ paths: that path is a Google Colab virtual mount and does
not exist on a local Windows machine. This script saves directly to OUTPUT_DIR on
local disk — no Google Drive is needed.

NOTE on GEE account registration: ee.Authenticate() will complete for any Google
account, but ee.Initialize() will fail if the account is not registered for Earth
Engine access. Register at https://earthengine.google.com/signup/ before first run.
"""

import time
from datetime import date
from pathlib import Path

import geopandas as gpd
from tqdm import tqdm

# ---------------------------------------------------------------------------
# Configuration — edit these as needed
# ---------------------------------------------------------------------------

YEAR              = 2020             # year to download; change here to update
BUFFER_KM_OPTIONS = [3, 2, 1]       # buffers tried in order (km); first that fits is used
SIZE_LIMIT_GB     = 2.0             # maximum estimated raw download size

COLLECTION        = "GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL"
N_BANDS           = 64              # A00-A63
RESOLUTION_M      = 10              # native 10 m pixel size
BYTES_PER_PIXEL   = 4               # float32

GEE_PROJECT       = "ee-tannerregan-gwu"            # set to your Google Cloud Project ID string if
                                    # ee.Initialize() raises an error about a missing project

BOUNDARY_SHP = Path(
    r"C:\Users\tanner_regan\Box\data_main\kigali_rehousing\source"
    r"\mpazi_project_maps\project_boundary.shp"
)
OUTPUT_DIR = Path("C:/Users/tanner_regan/downloads/kigali_downloads/google_satembed")

TILE_GRID_N   = 3    # fall back to NxN tile grid if single download fails
MAX_RETRIES   = 3    # retries per tile in tiled-download mode


# ---------------------------------------------------------------------------
# GEE authentication
# ---------------------------------------------------------------------------

def authenticate_gee() -> None:
    """
    Initialize the Earth Engine Python API using cached credentials.

    First run: calls ee.Authenticate(), which opens a browser for OAuth2 login
    and saves a token to %APPDATA%/earthengine/credentials. Subsequent runs load
    the cached token silently.

    Newer versions of earthengine-api (>=0.1.370) require a Google Cloud Project
    ID. If ee.Initialize() fails with "no project found", set GEE_PROJECT at the
    top of this script to your Cloud Project ID string. You can find it at
    https://console.cloud.google.com/ — it looks like "my-project-123".
    The project must have the Earth Engine API enabled.
    """
    import ee

    NO_PROJECT_MSG = (
        "\n[ERROR] ee.Initialize() requires a Google Cloud Project ID.\n"
        "  1. Go to https://console.cloud.google.com/ and find your project ID\n"
        "     (shown under the project name, e.g. 'my-project-123').\n"
        "  2. Make sure the Earth Engine API is enabled for that project:\n"
        "     https://console.cloud.google.com/apis/library/earthengine.googleapis.com\n"
        "  3. Set  GEE_PROJECT = 'your-project-id'  in the config block at the\n"
        "     top of this script, then re-run.\n"
    )

    kwargs = {"project": GEE_PROJECT} if GEE_PROJECT else {}

    def _initialize():
        try:
            ee.Initialize(**kwargs)
            return True
        except ee.EEException as exc:
            if "no project" in str(exc).lower():
                print(NO_PROJECT_MSG)
                raise SystemExit(1)
            return False  # some other EEException (e.g. missing credentials)

    if _initialize():
        print("[GEE] Initialized with cached credentials.")
        return

    print("[GEE] No cached credentials found — launching authentication flow...")
    ee.Authenticate()
    ee.Initialize(**kwargs)
    print("[GEE] Authentication complete.")


# ---------------------------------------------------------------------------
# Preflight size check
# ---------------------------------------------------------------------------

def estimate_size_gb(area_m2: float) -> float:
    """Conservative raw-size estimate: pixels * bands * bytes."""
    n_pixels = area_m2 / (RESOLUTION_M ** 2)
    return (n_pixels * N_BANDS * BYTES_PER_PIXEL) / 1e9


def preflight_aoi(boundary_shp: Path, buffer_km_options: list, size_limit_gb: float):
    """
    Load boundary shapefile, reproject to UTM-36S (EPSG:32736, correct for Kigali)
    for metric buffering, then try each buffer in order.

    Returns (ee_geom, buffer_km_used) for the first buffer that fits under size_limit_gb.
    Raises SystemExit if all options exceed the limit.
    """
    import ee

    print(f"\n[PREFLIGHT] Loading boundary: {boundary_shp}")
    if not boundary_shp.exists():
        raise FileNotFoundError(f"Boundary shapefile not found: {boundary_shp}")

    gdf = gpd.read_file(boundary_shp)
    gdf_utm = gdf.to_crs("EPSG:32736")  # UTM Zone 36S for Kigali

    for buf_km in buffer_km_options:
        buf_m = buf_km * 1000
        buffered = gdf_utm.buffer(buf_m)
        area_m2 = buffered.union_all().area
        size_gb = estimate_size_gb(area_m2)

        print(
            f"  Buffer {buf_km} km  →  "
            f"area {area_m2/1e6:.2f} km²  →  "
            f"estimated size {size_gb:.3f} GB"
        )

        if size_gb <= size_limit_gb:
            print(f"  [OK] {buf_km} km buffer selected.")
            # Convert back to WGS84 for GEE (expects lon/lat)
            buffered_wgs84 = buffered.to_crs("EPSG:4326")
            union_geom = buffered_wgs84.union_all()
            coords = list(union_geom.exterior.coords)  # [(lon, lat), ...]
            ee_geom = ee.Geometry.Polygon(coords)
            return ee_geom, buf_km

    print(f"\n[ABORT] All buffer options exceeded {size_limit_gb} GB limit.")
    raise SystemExit(1)


# ---------------------------------------------------------------------------
# Image selection
# ---------------------------------------------------------------------------

def select_image(collection: str, year: int, ee_geom):
    """
    Filter the annual collection to the target year and AOI, mosaic overlapping
    tiles, and clip to the AOI. Returns an ee.Image.

    GOOGLE_SATELLITE_EMBEDDING is tile-based (~163km x 163km per image tile).
    filterBounds() is essential: without it, .first() returns the alphabetically
    first tile in the collection, which may be anywhere in the world. mosaic()
    handles cases where the AOI spans more than one collection tile.
    """
    import ee

    print(f"\n[GEE] Selecting image: {collection}  year={year}")
    ic = (
        ee.ImageCollection(collection)
        .filterDate(f"{year}-01-01", f"{year}-12-31")
        .filterBounds(ee_geom)   # only tiles overlapping the AOI
    )

    tile_count = ic.size().getInfo()
    print(f"  Tiles found in AOI : {tile_count}")
    if tile_count == 0:
        raise RuntimeError(
            f"No tiles found for {collection} year={year} in the specified AOI. "
            "Check that the year is within the collection's coverage (2017-2024)."
        )

    image = ic.mosaic().clip(ee_geom)   # combine overlapping tiles, then clip

    info = image.getInfo()
    band_names = [b["id"] for b in info.get("bands", [])]
    print(f"  Band count : {len(band_names)} (expect {N_BANDS})")
    return image


# ---------------------------------------------------------------------------
# Filename builder
# ---------------------------------------------------------------------------

def build_filename(year: int, buffer_km: int, tile_suffix: str = "") -> str:
    """
    Build a self-describing filename.
    Examples:
      GOOGLE_SATELLITE_EMBEDDING_V1_ANNUAL_2020_mpazi_3km.tif
      GOOGLE_SATELLITE_EMBEDDING_V1_ANNUAL_2020_mpazi_3km_tile02.tif
    """
    base = f"GOOGLE_SATELLITE_EMBEDDING_V1_ANNUAL_{year}_mpazi_{buffer_km}km"
    if tile_suffix:
        base += f"_{tile_suffix}"
    return base + ".tif"


# ---------------------------------------------------------------------------
# Single-tile direct download
# ---------------------------------------------------------------------------

def download_single(image, ee_geom, out_path: Path) -> bool:
    """
    Attempt a single direct-to-disk download via geemap.ee_export_image().

    geemap wraps ee.data.getDownloadURL() which has a ~48 MB compressed limit.
    For this 64-band dataset the full AOI typically exceeds that limit, so this
    step usually fails and execution falls through to download_tiled(). The attempt
    is still worth making for small AOIs or future updates.

    A minimum size of 1 MB is required to reject near-empty stub files that GEE
    sometimes returns when the request exceeds its internal pixel limit.
    """
    import geemap

    MIN_BYTES = 1_000_000  # 1 MB — stubs from failed requests are typically < 10 KB

    print(f"\n[DOWNLOAD] Attempting single-tile download → {out_path.name}")
    try:
        geemap.ee_export_image(
            image,
            filename=str(out_path),
            scale=RESOLUTION_M,
            region=ee_geom,
            file_per_band=False,   # all 64 bands in one GeoTIFF
        )
        if out_path.exists() and out_path.stat().st_size >= MIN_BYTES:
            mb = out_path.stat().st_size / 1e6
            print(f"  [OK] {out_path.name}  ({mb:.1f} MB)")
            return True
        actual = out_path.stat().st_size if out_path.exists() else 0
        print(f"  [FAIL] File too small ({actual} bytes) — likely a stub from a size-exceeded request.")
        if out_path.exists():
            out_path.unlink()   # remove the stub so it doesn't pollute the output dir
        return False
    except Exception as exc:
        print(f"  [FAIL] Single download raised: {exc}")
        return False


# ---------------------------------------------------------------------------
# Tiled fallback download + GDAL mosaic
# ---------------------------------------------------------------------------

def make_tile_grid(ee_geom, n: int) -> list:
    """Subdivide the bounding box of ee_geom into n×n ee.Geometry.Rectangle tiles."""
    import ee

    bounds = ee_geom.bounds().getInfo()["coordinates"][0]
    lons = [pt[0] for pt in bounds]
    lats = [pt[1] for pt in bounds]
    lon_min, lon_max = min(lons), max(lons)
    lat_min, lat_max = min(lats), max(lats)

    lon_step = (lon_max - lon_min) / n
    lat_step = (lat_max - lat_min) / n

    tiles = []
    for row in range(n):
        for col in range(n):
            w = lon_min + col * lon_step
            e = w + lon_step
            s = lat_min + row * lat_step
            north = s + lat_step
            tiles.append(ee.Geometry.Rectangle([w, s, e, north]))
    return tiles


def download_tiled(image, ee_geom, year: int, buffer_km: int, out_path: Path) -> bool:
    """
    Download in TILE_GRID_N×TILE_GRID_N patches using ee.data.computePixels(), then
    mosaic with GDAL. Tiles already on disk with real data (>= MIN_TILE_BYTES) are
    skipped so interrupted downloads are resumable.

    ee.data.computePixels() is used instead of geemap.ee_export_image() because
    getDownloadURL() (used by geemap) silently produces near-empty stub files when
    the request exceeds GEE's per-request pixel limit for 64-band images.
    computePixels() specifies an explicit UTM grid and returns raw GeoTIFF bytes,
    which avoids both the stub-file problem and the south-up orientation issue.
    """
    import ee
    import ee.data          # explicitly import submodule (not auto-exposed by `import ee`)
    from osgeo import gdal
    from shapely.geometry import box

    MIN_TILE_BYTES = 10_000   # < 10 KB = empty stub, not real tile data
    MIN_MOSAIC_BYTES = 1_000_000  # < 1 MB = mosaic is empty/degenerate

    tiles_dir = out_path.parent / "_tiles"
    tiles_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n[DOWNLOAD] Tile-grid download ({TILE_GRID_N}×{TILE_GRID_N}) via computePixels API...")
    tile_geoms = make_tile_grid(ee_geom, TILE_GRID_N)
    tile_paths = []

    for i, tile_geom in enumerate(tqdm(tile_geoms, desc="  Downloading tiles", unit="tile")):
        tile_fname = build_filename(year, buffer_km, tile_suffix=f"tile{i:02d}")
        tile_path = tiles_dir / tile_fname

        if tile_path.exists() and tile_path.stat().st_size >= MIN_TILE_BYTES:
            mb = tile_path.stat().st_size / 1e6
            print(f"  [SKIP] Tile {i:02d} already on disk ({mb:.1f} MB).")
            tile_paths.append(tile_path.as_posix())
            continue

        # Get tile bounds in WGS84, convert to UTM-36S for an accurate metric grid.
        # Specifying the grid in UTM with scaleY=-RESOLUTION_M gives a standard
        # north-up GeoTIFF that GDAL can mosaic without orientation issues.
        bounds = tile_geom.bounds().getInfo()["coordinates"][0]
        lons = [p[0] for p in bounds]
        lats = [p[1] for p in bounds]
        tile_gdf = gpd.GeoDataFrame(
            geometry=[box(min(lons), min(lats), max(lons), max(lats))],
            crs="EPSG:4326",
        ).to_crs("EPSG:32736")
        x_min, y_min, x_max, y_max = tile_gdf.total_bounds
        width = max(1, round((x_max - x_min) / RESOLUTION_M))
        height = max(1, round((y_max - y_min) / RESOLUTION_M))

        for attempt in range(MAX_RETRIES):
            try:
                # Pass the ee.Image directly — computePixels() handles serialization
                # internally (double-encoding via ee.serializer.encode causes the
                # "does not evaluate to an image" error). The grid below defines the
                # spatial extent, so no .clip(tile_geom) is needed.
                params = {
                    "expression": image,
                    "fileFormat": "GEO_TIFF",
                    "grid": {
                        "dimensions": {"width": width, "height": height},
                        "affineTransform": {
                            "scaleX": RESOLUTION_M,
                            "shearX": 0,
                            "translateX": x_min,
                            "shearY": 0,
                            "scaleY": -RESOLUTION_M,
                            "translateY": y_max,
                        },
                        "crsCode": "EPSG:32736",
                    },
                }
                data = ee.data.computePixels(params)  # type: ignore[attr-defined]
                tile_path.write_bytes(data)

                if tile_path.stat().st_size >= MIN_TILE_BYTES:
                    mb = tile_path.stat().st_size / 1e6
                    print(f"  Tile {i:02d}: {mb:.1f} MB  ({width}×{height} px)")
                    tile_paths.append(tile_path.as_posix())
                    break
                print(
                    f"  [WARNING] Tile {i:02d} attempt {attempt+1}: "
                    f"result too small ({tile_path.stat().st_size} bytes)."
                )
            except Exception as exc:
                wait = 2 ** attempt
                print(f"  [WARNING] Tile {i:02d} attempt {attempt+1}: {exc} — retrying in {wait}s")
                time.sleep(wait)
        else:
            print(f"  [WARNING] Tile {i:02d} failed after {MAX_RETRIES} attempts — skipping.")

    if not tile_paths:
        print("  [FAIL] No tiles downloaded successfully.")
        return False

    print(f"\n[MOSAIC] Mosaicking {len(tile_paths)}/{len(tile_geoms)} tiles with GDAL...")
    gdal.Warp(
        out_path.as_posix(),
        tile_paths,
        format="GTiff",
        creationOptions=["COMPRESS=LZW", "TILED=YES"],
    )  # return value not held; GDAL flushes to disk when it goes out of scope

    if out_path.exists() and out_path.stat().st_size >= MIN_MOSAIC_BYTES:
        mb = out_path.stat().st_size / 1e6
        print(f"  [OK] Mosaic saved: {out_path.name}  ({mb:.1f} MB)")
        return True

    actual = out_path.stat().st_size if out_path.exists() else 0
    print(f"  [FAIL] Mosaic too small ({actual} bytes) — tiles may have contained no data.")
    return False


# ---------------------------------------------------------------------------
# Readme sidecar
# ---------------------------------------------------------------------------

def write_readme(out_path: Path, date_start: str, date_end: str, buffer_km: int, tiled: bool) -> None:
    """Write a provenance sidecar alongside the GeoTIFF."""
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
        f"CRS (as exported) : EPSG:4326 (WGS84, as returned by GEE)\n"
        f"Tiled download    : {'yes (patches merged with GDAL)' if tiled else 'no (single tile)'}\n"
        f"Output file       : {out_path.name}\n"
        f"Boundary shapefile: {BOUNDARY_SHP}\n"
        f"\n"
        f"About the dataset:\n"
        f"  Google Satellite Embedding V1 Annual is a 64-dimensional embedding derived\n"
        f"  from Sentinel-1, Sentinel-2, Landsat 8/9, GEDI, GLO-30 DEM, ERA5-Land,\n"
        f"  ALOS PALSAR-2, GRACE, and text data. All 64 bands form a single unit-length\n"
        f"  vector and must be used together; individual bands are not independently\n"
        f"  interpretable as spectral channels.\n"
        f"  Producer: Google / Google DeepMind.\n"
        f"  Temporal coverage: 2017-2024.\n"
    )
    readme.write_text(content, encoding="utf-8")
    print(f"  Readme written: {readme.name}")


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 65)
    print("Google Satellite Embedding Downloader")
    print(f"  Collection : {COLLECTION}")
    print(f"  Year       : {YEAR}")
    print(f"  Output     : {OUTPUT_DIR}")
    print("=" * 65)

    # 1. GEE authentication
    authenticate_gee()

    # 2. Preflight size check — select buffer
    ee_geom, buffer_km = preflight_aoi(BOUNDARY_SHP, BUFFER_KM_OPTIONS, SIZE_LIMIT_GB)

    # 3. Select and clip image
    image = select_image(COLLECTION, YEAR, ee_geom)

    # 4. Prepare output path
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / build_filename(YEAR, buffer_km)

    if out_path.exists() and out_path.stat().st_size > 0:
        print(f"\n[SKIP] Output already exists: {out_path}")
        print("  Delete the file or change YEAR / buffer settings to re-download.")
        return

    # 5. Attempt single-tile download; fall back to tiled if it fails
    tiled = False
    success = download_single(image, ee_geom, out_path)

    if not success:
        print(f"\n[FALLBACK] Single download failed. Trying {TILE_GRID_N}×{TILE_GRID_N} tile grid...")
        success = download_tiled(image, ee_geom, YEAR, buffer_km, out_path)
        tiled = True

    if not success:
        print(
            "\n[ERROR] All download strategies failed.\n"
            "  Check: GEE account access, Cloud Project ID (GEE_PROJECT), "
            "network, or try a smaller buffer."
        )
        raise SystemExit(1)

    # 6. Write readme sidecar
    write_readme(out_path, f"{YEAR}-01-01", f"{YEAR}-12-31", buffer_km, tiled)

    print("\n" + "=" * 65)
    print("Download complete.")
    print(f"  Output : {out_path}")
    print("=" * 65)


if __name__ == "__main__":
    main()
