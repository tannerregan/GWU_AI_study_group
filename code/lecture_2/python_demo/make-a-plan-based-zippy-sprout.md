# Plan: Prepare Sample Frame Script

## Context

This script constructs a spatially-matched sample frame for a household survey in Kigali, Rwanda. The Mpazi project area serves as the treated group; plots within a 1 km buffer outside the boundary are the candidate control group. The script filters that control pool using plot-size and land-use criteria, then estimates propensity scores from Google satellite embeddings so that treated and control households can be matched. The code is designed to be reused for two additional (as-yet-unknown) project areas by editing a single variable in `config.py`.

---

## Environment setup (first action)

Two packages are missing from the `kigali_rehousing` conda environment and must be installed before any other work:

```
conda install -n kigali_rehousing -c conda-forge rasterio contextily -y
conda env export -n kigali_rehousing   # strip prefix: line, overwrite kigali_rehousing_env.yml
```

---

## Files to create

| Path | Role |
|---|---|
| `code/01_prepare_sample_frame/config.py` | All project-specific and shared settings |
| `code/01_prepare_sample_frame/prepare_sample_frame.py` | Main script; one function per step |

---

## `config.py`

### Shared paths
```
SOURCE_DIR  = Path(r"C:\Users\tanner_regan\Box\data_main\kigali_rehousing\source")
GEN_DIR     = Path(r"C:\Users\tanner_regan\Box\data_main\kigali_rehousing\gen")
TEMP_DIR    = Path(r"C:\Users\tanner_regan\Box\data_main\kigali_rehousing\temp")
FIGURES_DIR = Path(r"C:\Users\tanner_regan\Documents\GitHub\kigali_rehousing\output\figures")
```

### Shared input files (same for all projects)
```
PLOTS_SHP    = SOURCE_DIR / "kigali_city_downloads_6may2026/Hosted_Kigali_Parcels_cc_layer0.shp"
LANDUSE_SHP  = SOURCE_DIR / "Masterplan2020_Zoning_Phases_22Apr2026_layer0.shp"
SATEMBED_DIR = SOURCE_DIR / "google_satembed"
```

### Shared analysis parameters
```
BUFFER_DIST_M        = 1000
PLOT_SIZE_PERCENTILE = 99
UTM_CRS              = "EPSG:32736"   # metric CRS for Kigali; used for all area/distance ops
```

### Per-project settings — add new projects here
```python
ACTIVE_PROJECT = "mpazi"   # ← change this to switch projects

PROJECTS = {
    "mpazi": {
        "project_name":  "mpazi",
        "satembed_year": 2020,   # year prior to construction start
        "boundary_shp":  SOURCE_DIR / "mpazi_project_maps/project_boundary.shp",
    },
    # Future projects added here, e.g.:
    # "project_b": {
    #     "project_name":  "project_b",
    #     "satembed_year": 2021,
    #     "boundary_shp":  SOURCE_DIR / "project_b_maps/project_boundary.shp",
    # },
}
```

---

## `prepare_sample_frame.py`

### Structure
- Top-level `main()` calls one function per step in sequence, passing outputs forward
- Each step function is clearly named and heavily commented
- All projections done in UTM-36S; reproject to WGS84 only for display/export
- Temp files written to `TEMP_DIR / project_name /`; deleted at end of `main()` only on success (leave on failure so intermediates can be inspected)

### Figure style helper
Applied globally before any plotting:
```python
plt.rcParams.update({
    "font.family":        "serif",
    "axes.spines.top":    False,
    "axes.spines.right":  False,
    "axes.grid":          False,
    "figure.dpi":         150,
    "figure.facecolor":   "white",
})
```
Maps use `ax.set_axis_off()`. All basemaps added via `contextily.add_basemap()`.

---

### Step 1 — Buffer and context maps

**Logic:**
- Load `boundary_shp` → reproject to UTM-36S → `.buffer(1000)` → reproject back to WGS84
- Save buffer polygon: `GEN_DIR / project_name / "buffer_1km.gpkg"`

**Figures (both maps share the same overlay style):**
- Project boundary: thick solid blue, topmost layer
- Buffer boundary: thick dashed blue, topmost layer
- `mpazi_01a_context_osm.png` — `contextily.providers.OpenStreetMap.Mapnik` basemap
- `mpazi_01b_context_satellite.png` — `contextily.providers.Esri.WorldImagery` basemap

---

### Step 2 — Plots within buffer

**Logic:**
1. Load plots shapefile → `gpd.clip()` to buffer
2. `in_project` column: `intersection(plot, boundary).area / plot.area >= 0.5` → 1, else 0
3. `large_plot` column: p99 of area computed on in-project plots only; flag = 1 if plot area > p99 (applied to all plots)

**Figures:**
- `mpazi_02a_plot_size_distribution.png` — overlapping semi-transparent KDE/histogram of plot area (m²), one series for in-project, one for outside
- `mpazi_02b_plots_map.png` — OSM basemap; blue boundary overlays (topmost); all buffer plots in thin black boundary; large plots in gray boundary + red diagonal hatch (`hatch="///"`)

**Output:** `GEN_DIR / project_name / "plots_buffer.gpkg"`

---

### Step 3 — Landuse within buffer

**Logic:**
1. Load landuse shapefile → `gpd.clip()` to buffer
2. `in_project` column: same ≥50% area logic as step 2
3. `zoning_feasible` column: collect `set(new_zoning)` from in-project polygons; flag = 1 if polygon's `new_zoning` is in that set

**Figure:**
- `mpazi_03_landuse_map.png` — OSM basemap; blue boundary overlays (topmost); **all** landuse polygons in the buffer drawn in two styles:
  - Feasible (`zoning_feasible = 1`): thin black boundary, fill colored by `new_zoning` (qualitative palette, legend)
  - Infeasible (`zoning_feasible = 0`): gray boundary, red diagonal hatch fill (`hatch="///"`)

**Output:** `GEN_DIR / project_name / "landuse_buffer.gpkg"`

---

### Step 4 — Analysis mask

**Logic:**
1. Start with buffer polygon
2. `mask = mask.difference(large_plots.union_all())` — remove large-plot footprints
3. `mask = mask.difference(infeasible_landuse.union_all())` — remove infeasible-zoning areas
4. Save: `GEN_DIR / project_name / "analysis_mask.gpkg"`

No figure for this step; the mask boundary is visible in the step-5 propensity map.

---

### Step 5 — Propensity scores from satellite embeddings

**5a — Load and mask satembed raster**
- Glob `SATEMBED_DIR` for `*_ANNUAL_{satembed_year}_*.tif` (pattern handles any buffer-size suffix in filename)
- Open with `rasterio.open()` — 64 bands (A00–A63), float32, UTM-36S, ~10 m pixels
- Reproject analysis mask to raster CRS; apply `rasterio.mask.mask()` to set pixels outside mask to nodata

**5b — Build per-pixel DataFrame**
- Read all 64 bands → numpy array `(64, H, W)`
- Rasterize project boundary onto same grid → `in_project` band (0/1), using `rasterio.features.rasterize()`
- Rasterize `new_zoning` values: build sorted `{zone_string: int}` mapping (saved to `GEN_DIR / project_name / "zoning_int_map.json"` for reproducibility); rasterize → `new_zoning_int` band
- Flatten to DataFrame; drop masked (nodata) pixels; columns: `in_project`, `new_zoning_int`, `A00`…`A63`

**5c — Probit model**
- One-hot encode `new_zoning_int` (drop one category as reference)
- X: zoning dummies + 64 satembed bands; y: `in_project`
- Fit `statsmodels.Probit(y, sm.add_constant(X)).fit()`; print summary to console
- Predict propensity scores for all unmasked pixels

**5d — Propensity score map**
- Reshape scores to `(H, W)` raster; write: `GEN_DIR / project_name / "propensity_scores.tif"`
- `mpazi_05a_propensity_map.png` — `imshow` with viridis colormap + colorbar; project boundary and buffer overlaid in blue (topmost)

**5e — Propensity score distribution**
- `mpazi_05b_propensity_distribution.png` — overlapping KDE of propensity scores, in-project vs. out-of-project, semi-transparent fills, clear legend

---

## Output file summary

```
Box/.../gen/mpazi/
  buffer_1km.gpkg
  plots_buffer.gpkg
  landuse_buffer.gpkg
  analysis_mask.gpkg
  propensity_scores.tif
  zoning_int_map.json

output/figures/
  mpazi_01a_context_osm.png
  mpazi_01b_context_satellite.png
  mpazi_02a_plot_size_distribution.png
  mpazi_02b_plots_map.png
  mpazi_03_landuse_map.png
  mpazi_05a_propensity_map.png
  mpazi_05b_propensity_distribution.png
```

Temp files: `Box/.../temp/mpazi/` — auto-deleted at end of successful run only.

---

## Verification

1. Run `python code/01_prepare_sample_frame/prepare_sample_frame.py` in the `kigali_rehousing` conda environment
2. Confirm all 7 figures appear in `output/figures/` with correct content
3. Confirm all 6 gen files appear in `Box/.../gen/mpazi/`
4. Confirm `Box/.../temp/mpazi/` was cleaned up (does not exist or is empty)
5. To test multi-project adaptability: change `ACTIVE_PROJECT` in `config.py` to a new project name and confirm the script raises a clear `KeyError` with a helpful message (not a silent failure)
