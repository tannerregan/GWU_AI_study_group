# Plan: Google Earth Engine Satellite Embedding Downloader

## Context
The Kigali rehousing project needs satellite embedding rasters (GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL) to support spatial analysis of slum redevelopment. This script downloads the data for the Mpazi project area as a georeferenced GeoTIFF for year 2020, with the year configurable for future multi-year downloads.

## Key Research Findings

**Direct local download IS possible** via `geemap.ee_export_image()`. This function wraps GEE's `getDownloadURL()` and streams the response directly to local disk — no Google Drive required. The `/content/drive/` path mentioned in the prompt is a Google Colab virtual mount path that does not exist on a local Windows machine; it is not used here.

**Dataset**: GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL — 64 bands (A00–A63), 10 m resolution, float32, years 2017–2024. The Mpazi neighborhood with a 3 km buffer covers roughly 700×700 pixels × 64 bands × 4 bytes ≈ 125 MB — well under the 2 GB limit.

**New packages needed**: `earthengine-api` and `geemap` (neither is in the current env).

---

## Files to Create / Modify

| Path | Action |
|------|--------|
| `code/02_google_satembed_download/download_satellite_embedding.py` | Create (new script) |
| `kigali_rehousing_env.yml` | Update (re-export after conda install) |

---

## Implementation Plan

### Step 1: Environment update
```bash
conda install -n kigali_rehousing -c conda-forge earthengine-api geemap -y
conda env export -n kigali_rehousing | grep -v "^prefix:" > kigali_rehousing_env.yml
```
Install both packages together so conda resolves their joint dependency graph. `geemap` brings `rioxarray`, `xarray`, `ipyleaflet` as transitive deps — these are benign. Re-export with full pinned build strings per CLAUDE.md instructions.

### Step 2: Script structure (mirrors `download_kigali_gis.py` patterns)

**Config block** at top of script (easy to change):
```python
YEAR           = 2020
BUFFER_KM_OPTIONS = [3, 2, 1]   # tried in order; first that fits is used
SIZE_LIMIT_GB  = 2.0
COLLECTION     = "GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL"
N_BANDS        = 64
RESOLUTION_M   = 10
BYTES_PER_PIXEL = 4              # float32
GEE_PROJECT    = None            # set if ee.Initialize() requires a Cloud Project ID
BOUNDARY_SHP   = Path(r"C:\Users\tanner_regan\Box\data_main\kigali_rehousing\source\mpazi_project_maps\project_boundary.shp")
OUTPUT_DIR     = Path("C:/Users/tanner_regan/downloads/kigali_downloads/google_satembed")
TILE_GRID_N    = 3               # NxN tile fallback if single download fails
```

**Functions:**

1. `authenticate_gee()` — Try `ee.Initialize()`; if it raises `EEException`, call `ee.Authenticate()` then `ee.Initialize()`. On first run opens browser. Token cached at `%APPDATA%/earthengine/credentials`. Note: GEE account must be registered at earthengine.google.com/signup before first run.

2. `estimate_size_gb(area_m2)` — `(area_m2 / 100 * 64 * 4) / 1e9`

3. `preflight_aoi(boundary_shp, buffer_km_options, size_limit_gb)` — Load shapefile, reproject to **EPSG:32736** (UTM Zone 36S, correct for Kigali) for metric buffering, try each buffer in order, convert back to WGS84 for GEE. Returns `(ee_geom, buffer_km_used)`.

4. `select_image(collection, year, ee_geom)` — `ee.ImageCollection(collection).filterDate(...).sort("system:time_start").first().clip(ee_geom)`. Call `.getInfo()` to verify image exists and log band count.

5. `build_filename(year, buffer_km, tile_suffix="")` — Returns e.g. `GOOGLE_SATELLITE_EMBEDDING_V1_ANNUAL_2020_mpazi_3km.tif`

6. `download_single(image, ee_geom, out_path, resolution_m)` — Calls `geemap.ee_export_image(image, filename=str(out_path), scale=resolution_m, region=ee_geom, file_per_band=False)`. Returns `True` if file exists with size > 0.

7. `make_tile_grid(ee_geom, n)` — Subdivide bounding box of AOI into n×n `ee.Geometry.Rectangle` tiles.

8. `download_tiled(image, ee_geom, n, year, buffer_km, out_path, resolution_m)` — Download each tile into `OUTPUT_DIR/_tiles/`, skip if already exists (resumable). Mosaic with GDAL: `gdal.BuildVRT()` + `gdal.Translate(..., creationOptions=["COMPRESS=LZW", "TILED=YES"])`. `osgeo.gdal` is already in the env (`gdal=3.6.2`). Returns `True` on success.

9. `write_readme(out_path, year, buffer_km, tiled)` — Write `[stem]_readme.txt` sidecar with: source URL, exact catalog link, download date, collection, year, buffer, bands, resolution, tiled flag, output filename, boundary shapefile path, CRS.

10. `main()` — Orchestrate: authenticate → preflight → select image → check if output exists (skip if so) → try `download_single()` → if fails, try `download_tiled()` → `write_readme()`. Print descriptive progress messages throughout.

---

## Tricky / Important Details

- **UTM zone**: EPSG:32736 (UTM 36S) for Kigali — buffer must be done in a projected CRS, not WGS84.
- **GEE coordinate order**: GEE expects `[lon, lat]`. Shapely in EPSG:4326 gives `(x, y)` = `(lon, lat)`, so this is correct.
- **`file_per_band=False`**: Always pass explicitly — if `True`, creates 64 separate files.
- **`ee.Initialize(project=...)`**: Newer `earthengine-api` versions require a Cloud Project ID. Add `GEE_PROJECT` config var; if `None`, call `ee.Initialize()` without it and let it fail with a clear message prompting the user to set it.
- **First-run note in docstring**: GEE account must be registered; `ee.Authenticate()` succeeds for any Google account but `ee.Initialize()` will fail for unregistered accounts.
- **`/content/drive/` path**: Note explicitly in script docstring that this is a Colab-only path not applicable on local Windows — this script saves directly to `OUTPUT_DIR`.
- **GDAL paths on Windows**: Pass `path.as_posix()` to GDAL functions to avoid backslash issues.

---

## Output

For year 2020, 3 km buffer:
- `C:/Users/tanner_regan/downloads/kigali_downloads/google_satembed/GOOGLE_SATELLITE_EMBEDDING_V1_ANNUAL_2020_mpazi_3km.tif`
- `C:/Users/tanner_regan/downloads/kigali_downloads/google_satembed/GOOGLE_SATELLITE_EMBEDDING_V1_ANNUAL_2020_mpazi_3km_readme.txt`

---

## Verification

1. Run `conda env export -n kigali_rehousing | findstr earthengine` to confirm packages installed.
2. Run `python download_satellite_embedding.py` — confirm auth flow completes (first run opens browser).
3. Confirm preflight prints size estimates for each buffer option and selects 3 km.
4. Confirm output `.tif` exists with non-zero size.
5. Open output with `geopandas`/`rasterio` or QGIS to verify: 64 bands, 10 m resolution, correct spatial extent over Kigali.
6. Verify `_readme.txt` sidecar was written alongside the `.tif`.
