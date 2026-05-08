# Plan: Step 6 — Sample Frame Construction

## Context
The pipeline currently ends at Step 5 (propensity scores). This adds Step 6, which converts the spatial analysis into an actual sampling frame: a hexagonal grid filtered down to residential land within the buffer, with signed distances to the project boundary and two output figures.

---

## Critical files
- `code/01_prepare_sample_frame/prepare_sample_frame.py` — add `step6_sample_frame()` function and call it from `main()`
- `code/01_prepare_sample_frame/config.py` — add `HEX_SIZE_M` constant

---

## Change 1 — config.py: add hex size constant

```python
# Circumradius of each hexagon in the sampling grid (metres, centre to corner)
HEX_SIZE_M = 100
```

---

## Change 2 — prepare_sample_frame.py: add `_make_hex_grid()` helper

Add a module-level helper (alongside `_place_legend`) that generates a GeoDataFrame of hexagons covering a bounding box. Uses shapely + numpy — no new dependencies.

```python
def _make_hex_grid(bounds, hex_size_m: float, crs) -> gpd.GeoDataFrame:
    """
    Generate a flat-top hexagonal grid covering bounds (xmin,ymin,xmax,ymax).
    hex_size_m is the circumradius (centre to corner) in CRS units.
    """
    from shapely.geometry import Polygon
    dx = hex_size_m * np.sqrt(3)   # horizontal spacing between column centres
    dy = hex_size_m * 1.5          # vertical spacing between row centres
    xmin, ymin, xmax, ymax = bounds

    hexes = []
    row = 0
    y = ymin
    while y <= ymax + hex_size_m:
        x_offset = dx / 2 if row % 2 else 0.0
        x = xmin
        while x <= xmax + hex_size_m:
            cx, cy = x + x_offset, y
            # 6 corners of a flat-top hexagon
            angles = np.pi / 6 + np.linspace(0, 2 * np.pi, 7)[:-1]
            coords = [(cx + hex_size_m * np.cos(a),
                       cy + hex_size_m * np.sin(a)) for a in angles]
            hexes.append(Polygon(coords))
            x += dx
        y += dy
        row += 1

    return gpd.GeoDataFrame(geometry=hexes, crs=crs)
```

---

## Change 3 — prepare_sample_frame.py: add `step6_sample_frame()` function

Signature:
```python
def step6_sample_frame(proj, boundary_wgs, buffer_wgs, plots_utm, p_upper,
                       landuse_utm, gen_dir, figures_dir):
```

### 6a — Hexagonal grid covering the buffer
1. Generate with `_make_hex_grid(buffer_utm.total_bounds, config.HEX_SIZE_M, config.UTM_CRS)`.
2. Keep only hexagons whose **centroid** intersects the buffer polygon:
   ```python
   buffer_poly = buffer_utm.union_all()
   hexgrid = hexgrid[hexgrid.centroid.intersects(buffer_poly)].copy()
   ```

### 6b — Remove hexagons with centroid inside a large plot
Large plots = `plots_utm[plots_utm["area_m2"] > p_upper]` (upper cutoff only — the lower-cutoff small plots are irrelevant here).
```python
large_plot_union = plots_utm[plots_utm["area_m2"] > p_upper].union_all()
hexgrid = hexgrid[~hexgrid.centroid.within(large_plot_union)].copy()
```

### 6c — Residential landuse layer (morphological closing)
Select R1 + R2 polygons, union, then close gaps with a 20m out / 20m in buffer:
```python
residential = landuse_utm[landuse_utm["zone_code"].isin(["R1", "R2"])]
residential_closed = residential.union_all().buffer(20).buffer(-20)
```

### 6d — Filter to residential area → sample frame
```python
hexgrid = hexgrid[hexgrid.centroid.within(residential_closed)].copy()
```

### 6e — Add `in_project` and `dist_to_boundary` columns
```python
boundary_poly = boundary_utm.union_all()
boundary_line = boundary_poly.boundary

hexgrid["centroid_geom"] = hexgrid.centroid   # temp column
hexgrid["in_project"] = hexgrid["centroid_geom"].within(boundary_poly).astype(int)
hexgrid["dist_to_boundary"] = hexgrid["centroid_geom"].apply(
    lambda c: -c.distance(boundary_line) if c.within(boundary_poly)
               else c.distance(boundary_line)
)
hexgrid = hexgrid.drop(columns=["centroid_geom"])
```

### 6f — Save sample frame
Save to `gen_dir / "sample_frame.gpkg"` (WGS84). Print count of total hexagons, inside-project hexagons, outside hexagons.

### 6g — Figure 06a: sample frame map
Follow exact style of Steps 2/3 maps:
- OSM basemap via contextily
- Draw hexagons: `facecolor="none", edgecolor="black", linewidth=0.4, zorder=3`
- Buffer ring (dashed blue, zorder=10) and project boundary (solid blue, zorder=11) on top
- Legend via `_place_legend()` with `LEGEND_STYLE_LIGHT`
- Filename: `{project_name}_06a_sample_frame_map.png`

### 6h — Figure 06b: distance histogram
- Compute bin edges: `np.arange(floor_100m, ceil_100m + 100, 100)` spanning the full range of `dist_to_boundary`, snapped to 100m
- Use `ax.hist(dist_to_boundary, bins=bin_edges, ...)` with a vertical line at x=0 labelled "Project boundary"
- Colour bars inside boundary (#1a6faf, matching BOUNDARY_COLOUR) differently from outside (#e07b39) — achieved via two overlapping `ax.hist()` calls, one for `dist ≤ 0`, one for `dist > 0`
- x-axis label: "Distance to project boundary (m) — negative = inside"
- y-axis label: "Number of hexagons"
- Legend via `_place_legend()` placed outside axes to the right (same pattern as distribution figures)
- Filename: `{project_name}_06b_distance_histogram.png`

---

## Change 4 — main(): call step6 after step4

```python
step6_sample_frame(
    proj, boundary_wgs, buffer_wgs, plots_utm, p_upper,
    landuse_utm, gen_dir, figures_dir
)
```
`step6` does not need `mask_wgs` or Step 5 outputs — it can run in parallel order-wise but we keep it sequential after step4 for clarity.

Also update the module docstring Step list to include Step 6.

---

## Verification

1. `conda activate kigali_rehousing && python code/01_prepare_sample_frame/prepare_sample_frame.py`
2. Check `Box/.../gen/mpazi/sample_frame.gpkg` exists and opens in QGIS with correct geometry and columns (`in_project`, `dist_to_boundary`).
3. Check `output/figures/mpazi_06a_sample_frame_map.png` — hexagons visible over OSM basemap.
4. Check `output/figures/mpazi_06b_distance_histogram.png` — x-axis spans negative (inside) to ~+1000m; bars coloured by side of boundary.
