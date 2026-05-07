"""
Download GIS data from the Kigali City Master Plan ArcGIS REST API.

Step 1: Enumerate and print all FeatureServer layers across both base URLs.
Step 2: Download each layer as a shapefile (geometry layers) or CSV (tables).

Output directory: C:/Users/tanner_regan/downloads/kigali_downloads/
"""

import time
import json
from datetime import date
from pathlib import Path

import requests
import geopandas as gpd
import pandas as pd
from tqdm import tqdm

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URLS = [
    "https://masterplan.kigalicity.gov.rw/server/rest/services/Hosted",
    "https://masterplan.kigalicity.gov.rw/server/rest/services/Masterplan2020",
]
OUTPUT_DIR = Path("C:/Users/tanner_regan/downloads/kigali_downloads")
BATCH_SIZE = 500    # objectIds per paginated request
REQUEST_DELAY = 1.5 # seconds between batch requests
MAX_RETRIES = 3


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_json(url: str, params: dict = None, retries: int = MAX_RETRIES) -> dict | None:
    """GET a URL with retry + exponential backoff. Returns parsed JSON or None."""
    params = params or {}
    params.setdefault("f", "json")
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                print(f"  [API error] {url}: {data['error']}")
                return None
            return data
        except Exception as exc:
            wait = 2 ** attempt
            print(f"  [Attempt {attempt+1}/{retries}] {exc} — retrying in {wait}s")
            time.sleep(wait)
    print(f"  [FAILED] Could not reach {url}")
    return None


def safe_name(folder: str, service_name: str) -> str:
    """Convert e.g. 'Hosted', 'Kigali_Parcels_cc' → 'Hosted_Kigali_Parcels_cc'."""
    svc_short = service_name.split("/")[-1]
    return f"{folder}_{svc_short}"


def write_readme(filepath: Path, source_url: str, layer_name: str, feature_count: int) -> None:
    readme = filepath.with_name(filepath.stem + "_readme.txt")
    readme.write_text(
        f"Source: {source_url}\n"
        f"Layer: {layer_name}\n"
        f"Features downloaded: {feature_count}\n"
        f"Download date: {date.today().isoformat()}\n"
    )


# ---------------------------------------------------------------------------
# Step 1 — Enumerate FeatureServers
# ---------------------------------------------------------------------------

def discover_feature_servers(base_urls: list[str]) -> list[dict]:
    """
    Returns a list of dicts, one per layer/table:
      {folder, service_name, service_url, layer_id, layer_name, has_geometry}
    Also prints the discovered structure.
    """
    all_layers = []

    for base_url in base_urls:
        folder = base_url.rstrip("/").split("/")[-1]
        print(f"\n{'='*60}")
        print(f"Scanning: {base_url}")
        print(f"{'='*60}")

        catalog = get_json(base_url)
        if catalog is None:
            continue

        feature_services = [s for s in catalog.get("services", []) if s["type"] == "FeatureServer"]
        print(f"Found {len(feature_services)} FeatureServer(s):\n")

        for svc in feature_services:
            svc_name = svc["name"]            # e.g. "Hosted/Kigali_Parcels_cc"
            svc_url = f"{base_url}/{svc_name.split('/')[-1]}/FeatureServer"
            print(f"  {svc_name}/FeatureServer")

            fs_info = get_json(svc_url)
            if fs_info is None:
                print(f"    [SKIP] Could not read service metadata")
                continue
            time.sleep(0.5)

            layers = fs_info.get("layers", [])
            tables = fs_info.get("tables", [])

            if not layers and not tables:
                print(f"    (no layers or tables found)")
                continue

            for lyr in layers:
                geom_type = lyr.get("geometryType", "unknown")
                print(f"    Layer {lyr['id']}: \"{lyr['name']}\" ({geom_type})")
                all_layers.append({
                    "folder": folder,
                    "service_name": svc_name,
                    "service_url": svc_url,
                    "layer_id": lyr["id"],
                    "layer_name": lyr["name"],
                    "has_geometry": True,
                })

            for tbl in tables:
                print(f"    Table {tbl['id']}: \"{tbl['name']}\" (no geometry)")
                all_layers.append({
                    "folder": folder,
                    "service_name": svc_name,
                    "service_url": svc_url,
                    "layer_id": tbl["id"],
                    "layer_name": tbl["name"],
                    "has_geometry": False,
                })

    return all_layers


# ---------------------------------------------------------------------------
# Step 2a — Pre-flight check
# ---------------------------------------------------------------------------

def preflight_check(layer_url: str) -> tuple[bool, int]:
    """
    Returns (ok, feature_count). Tries a count query and a 1-record fetch.
    """
    count_data = get_json(f"{layer_url}/query", {"where": "1=1", "returnCountOnly": "true"})
    if count_data is None or "count" not in count_data:
        print(f"  [PREFLIGHT FAIL] Could not get count from {layer_url}")
        return False, 0

    count = count_data["count"]

    sample = get_json(f"{layer_url}/query", {
        "where": "1=1",
        "outFields": "*",
        "resultRecordCount": 1,
    })
    if sample is None:
        print(f"  [PREFLIGHT FAIL] Could not fetch sample record from {layer_url}")
        return False, 0

    return True, count


# ---------------------------------------------------------------------------
# Step 2b — Download a geometry layer (shapefile output)
# ---------------------------------------------------------------------------

def download_geometry_layer(layer_url: str, layer_info: dict, feature_count: int) -> Path | None:
    """Paginate via objectIds, accumulate GeoJSON, write shapefile."""
    fname_stem = safe_name(layer_info["folder"], layer_info["service_name"])
    fname_stem += f"_layer{layer_info['layer_id']}"
    out_path = OUTPUT_DIR / f"{fname_stem}.shp"

    print(f"\n  Downloading {feature_count:,} features → {out_path.name}")

    # Get all objectIds
    ids_data = get_json(f"{layer_url}/query", {"where": "1=1", "returnIdsOnly": "true"})
    if ids_data is None or "objectIds" not in ids_data:
        print("  [ERROR] Could not retrieve objectIds")
        return None
    object_ids = ids_data["objectIds"]
    time.sleep(REQUEST_DELAY)

    # Batch download
    all_features = []
    batches = [object_ids[i:i + BATCH_SIZE] for i in range(0, len(object_ids), BATCH_SIZE)]
    crs = None

    for batch in tqdm(batches, desc=f"  {layer_info['layer_name']}", unit="batch"):
        ids_str = ",".join(str(oid) for oid in batch)
        data = get_json(f"{layer_url}/query", {
            "objectIds": ids_str,
            "outFields": "*",
            "f": "geojson",
        })
        if data is None:
            print(f"  [WARNING] Batch failed, skipping {len(batch)} features")
            time.sleep(REQUEST_DELAY)
            continue

        features = data.get("features", [])
        all_features.extend(features)

        if crs is None and "crs" in data:
            crs = data["crs"]

        time.sleep(REQUEST_DELAY)

    if not all_features:
        print("  [ERROR] No features collected")
        return None

    print(f"  Building GeoDataFrame from {len(all_features):,} features...")
    geojson_fc = {"type": "FeatureCollection", "features": all_features}
    gdf = gpd.GeoDataFrame.from_features(geojson_fc["features"])

    # Set/reproject CRS to WGS84
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    elif gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs("EPSG:4326")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(out_path, driver="ESRI Shapefile")
    print(f"  Saved: {out_path}")

    write_readme(out_path, f"{layer_url}/query", layer_info["layer_name"], len(all_features))
    return out_path


# ---------------------------------------------------------------------------
# Step 2c — Download a table (CSV output)
# ---------------------------------------------------------------------------

def download_table(layer_url: str, layer_info: dict, feature_count: int) -> Path | None:
    """Download a non-geometry table as CSV using resultOffset pagination."""
    fname_stem = safe_name(layer_info["folder"], layer_info["service_name"])
    fname_stem += f"_table{layer_info['layer_id']}"
    out_path = OUTPUT_DIR / f"{fname_stem}.csv"

    print(f"\n  Downloading table ({feature_count:,} rows) → {out_path.name}")

    all_rows = []
    offset = 0

    with tqdm(total=feature_count, desc=f"  {layer_info['layer_name']}", unit="rows") as pbar:
        while True:
            data = get_json(f"{layer_url}/query", {
                "where": "1=1",
                "outFields": "*",
                "resultOffset": offset,
                "resultRecordCount": BATCH_SIZE,
            })
            if data is None:
                print(f"  [WARNING] Request failed at offset {offset}")
                break

            rows = data.get("features", [])
            if not rows:
                break

            all_rows.extend([r["attributes"] for r in rows])
            pbar.update(len(rows))
            offset += len(rows)

            if len(rows) < BATCH_SIZE:
                break
            time.sleep(REQUEST_DELAY)

    if not all_rows:
        print("  [ERROR] No rows collected")
        return None

    df = pd.DataFrame(all_rows)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    print(f"  Saved: {out_path}")

    write_readme(out_path, f"{layer_url}/query", layer_info["layer_name"], len(all_rows))
    return out_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Step 1: Discover all FeatureServer layers
    all_layers = discover_feature_servers(BASE_URLS)

    print(f"\n{'='*60}")
    print(f"Total layers/tables to download: {len(all_layers)}")
    print(f"Output directory: {OUTPUT_DIR}")
    print(f"{'='*60}\n")

    # Step 2: Download each
    for i, layer_info in enumerate(all_layers, 1):
        layer_url = f"{layer_info['service_url']}/{layer_info['layer_id']}"
        label = f"[{i}/{len(all_layers)}] {layer_info['service_name']} / {layer_info['layer_name']}"
        print(f"\n{label}")

        ok, count = preflight_check(layer_url)
        if not ok:
            print(f"  [SKIP] Pre-flight check failed")
            continue

        print(f"  Pre-flight OK — {count:,} features/rows")
        time.sleep(REQUEST_DELAY)

        if layer_info["has_geometry"]:
            download_geometry_layer(layer_url, layer_info, count)
        else:
            download_table(layer_url, layer_info, count)

    print(f"\n{'='*60}")
    print("Download complete.")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
