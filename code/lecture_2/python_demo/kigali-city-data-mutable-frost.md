# Plan: Kigali City Master Plan GIS Scraper

## Context
The Kigali City Master Plan website exposes GIS data via an ESRI ArcGIS REST API. The goal is to enumerate all FeatureServer endpoints across two base URLs, then download each layer to local shapefiles with provenance metadata. This data will support the Kigali rehousing research project's spatial analysis.

---

## Discovered FeatureServer Structure

```
Hosted/
├── Incentive_Zoning_GCK/FeatureServer
│   └── Layer 140: "Incentive Zoning"          (Polygon, 709 features)
├── Kigali_Parcels_cc/FeatureServer
│   └── Layer 0:   "Kigali Parcels"            (Polygon, 551,359 features, max 2,000/request)
├── Kigali_Parcels_no_upi/FeatureServer
│   └── Layer 0:   "Kigali Parcels"            (Polygon, 551,359 features, max 1,000/request)
├── Rda_Districts_names/FeatureServer
│   └── Table 0:   "Rda_Districts_names"       (no geometry — table only)
└── WorldCountries/FeatureServer
    └── Table 0:   "WorldCountries"             (no geometry — table only)

Masterplan2020/
├── Zoning_Phases_18March2026/FeatureServer
│   └── Layer 0: "Zoning_Phases_18March2026"  (Polygon, 8,179 features)
└── Zoning_Phases_22Apr2026/FeatureServer
    └── Layer 0: "Zoning_Phases_22Apr2026"    (Polygon, 8,180 features)
```

Note on MapServers: MapServers are rendering/tile services only — they have no query endpoint for downloading raw vector data. Excluding them is correct.

Note on tables (Rda_Districts_names, WorldCountries): These are attribute tables with no geometry. They will be downloaded as CSV files rather than shapefiles.

---

## Implementation Plan

### Files to create
- [code/02_gis_download/download_kigali_gis.py](code/02_gis_download/download_kigali_gis.py) — single script covering enumeration + download

### Environment changes
Add to [kigali_rehousing_env.yml](kigali_rehousing_env.yml):
- `geopandas` — reads GeoJSON features, writes shapefiles
- `shapely` — geometry dependency of geopandas
- `fiona` — shapefile I/O dependency of geopandas
- `pyproj` — CRS/projection dependency of geopandas

`requests` and `tqdm` are already present.

---

### Script design

**Constants (top of file)**
```python
BASE_URLS = [
    "https://masterplan.kigalicity.gov.rw/server/rest/services/Hosted",
    "https://masterplan.kigalicity.gov.rw/server/rest/services/Masterplan2020",
]
OUTPUT_DIR = Path("C:/Users/tanner_regan/downloads/kigali_downloads")
BATCH_SIZE = 500          # objectIds per paginated request (conservative)
REQUEST_DELAY = 1.5       # seconds between requests
MAX_RETRIES = 3
```

**Step 1 — Enumerate FeatureServers** (`discover_feature_servers`)
- GET `{base_url}?f=json` for each base URL
- Filter `services` where `type == "FeatureServer"`
- For each FeatureServer, GET `{base_url}/{name}/FeatureServer?f=json`
- Collect layers (with geometry) and tables (no geometry) separately
- Print the full discovered structure

**Step 2 — Pre-flight check** (`preflight_check`)
- For each layer: GET `query?where=1=1&returnCountOnly=true&f=json` → confirm count
- Fetch 1 record (`resultRecordCount=1`) to confirm query works and check field structure
- If either fails, skip with a warning (do not abort entire run)

**Step 3 — Download with objectId pagination** (`download_layer`)
For geometry layers:
1. GET `query?where=1=1&returnIdsOnly=true&f=json` → list of all objectIds
2. Split into batches of `BATCH_SIZE`
3. For each batch: GET `query?objectIds={ids}&outFields=*&f=geojson`
4. Accumulate features into a list
5. Build a GeoDataFrame from all features; reproject to WGS84 (EPSG:4326) if needed
6. Write shapefile to `OUTPUT_DIR/{safe_name}.shp` (geopandas `.to_file()`)
7. `time.sleep(REQUEST_DELAY)` between batches
8. Use `tqdm` progress bar over batches; print counts at start and end

For attribute tables (no geometry):
1. GET `query?where=1=1&outFields=*&f=json` (paginated with `resultOffset` if needed)
2. Save as CSV

**Step 4 — Write readme** (`write_readme`)
- Create `{filename}_readme.txt` alongside each output file
- Content: source URL, layer name, feature count, download date (ISO format)

**File naming convention**
`{ServiceFolder}_{ServiceName}_layer{LayerID}` → e.g.:
- `Hosted_Kigali_Parcels_cc_layer0.shp`
- `Masterplan2020_Zoning_Phases_22Apr2026_layer0.shp`
- `Hosted_Rda_Districts_names_table0.csv`

**Rate-limit / error protection**
- Retry up to `MAX_RETRIES` times with exponential backoff on any HTTP error
- Check HTTP status codes; log and skip on persistent failure
- Pre-flight check before committing to full download
- `time.sleep(REQUEST_DELAY)` between every batch request

---

## Verification

1. Run the script with `conda activate kigali_rehousing && python code/02_gis_download/download_kigali_gis.py`
2. Confirm printed FeatureServer structure matches the table above
3. Confirm `C:/Users/tanner_regan/downloads/kigali_downloads/` contains `.shp` (+ `.dbf`, `.shx`, `.prj`) and `_readme.txt` files for each layer
4. Spot-check one shapefile: `import geopandas as gpd; gdf = gpd.read_file("...shp"); print(gdf.shape, gdf.crs)`
5. Verify the Kigali_Parcels layers have ~551,359 rows (confirming pagination worked)
