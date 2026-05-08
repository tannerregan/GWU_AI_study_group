"""
Prepare a spatially-matched sample frame for a household survey in Kigali.

Workflow
--------
  Step 1 — Buffer the project boundary by 1 km and produce two context maps
            (OSM and satellite basemaps).
  Step 2 — Subset city parcels (plots) to the buffer area; flag excluded plots.
  Step 3 — Subset landuse polygons to the buffer area; flag non-R2 zoning.
  Step 4 — Build a binary analysis mask by subtracting excluded-plot and
            non-R2-zoning areas from the buffer polygon.
  Step 5 — Estimate pixel-level propensity scores from Google satellite
            embeddings using a probit model.
  Step 6 — Build the sample frame: hexagonal grid filtered to residential land,
            with signed distances to the project boundary.

All project-specific settings live in config.py. To run for a different
project, change ACTIVE_PROJECT there and re-run this script.

Output
------
  Figures  → output/figures/  (committed to the GitHub repo)
  Gen data → Box/.../gen/{project_name}/
  Temp     → Box/.../temp/{project_name}/  (auto-deleted on success)

Usage
-----
  conda activate kigali_rehousing
  python code/01_prepare_sample_frame/prepare_sample_frame.py
"""

import shutil
from pathlib import Path

import contextily as ctx
import geopandas as gpd
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
import rasterio.features
import rasterio.mask
import rasterio.warp
import statsmodels.api as sm
from matplotlib.lines import Line2D
from scipy.stats import gaussian_kde
from shapely.geometry import mapping

import config

# ---------------------------------------------------------------------------
# Global figure style (translated from Kieran Healy's socviz.co style guide)
# Clean white background, serif font, high data-ink ratio, minimal chrome.
# ---------------------------------------------------------------------------

plt.rcParams.update({
    "font.family":        "serif",
    "font.size":          11,
    "axes.spines.top":    False,
    "axes.spines.right":  False,
    "axes.grid":          False,
    "figure.dpi":         150,
    "figure.facecolor":   "white",
    "axes.facecolor":     "white",
    "legend.frameon":     True,
    "legend.fontsize":    11,
})

# Colour constants used throughout
BOUNDARY_COLOUR = "#1a6faf"   # solid blue for project boundary
BUFFER_COLOUR   = "#1a6faf"   # dashed blue for buffer ring
HATCH_COLOUR    = "#cc0000"   # red diagonal hatch for excluded polygons

# ---------------------------------------------------------------------------
# Legend style helpers
# ---------------------------------------------------------------------------

LEGEND_STYLE_LIGHT = dict(
    frameon=True, facecolor="white", framealpha=0.85,
    edgecolor="#999999", fontsize=11,
)
LEGEND_STYLE_DARK = dict(
    frameon=True, facecolor="#333333", framealpha=0.85,
    edgecolor="#555555", fontsize=11, labelcolor="white",
)


def _make_hex_grid(bounds: tuple, hex_size_m: float, crs) -> gpd.GeoDataFrame:
    """
    Generate a flat-top hexagonal grid covering bounds (xmin, ymin, xmax, ymax).
    hex_size_m is the circumradius (centre to corner) in CRS units.
    """
    from shapely.geometry import Polygon as ShapelyPolygon
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
            angles = np.pi / 6 + np.linspace(0, 2 * np.pi, 7)[:-1]
            coords = [(cx + hex_size_m * np.cos(a),
                       cy + hex_size_m * np.sin(a)) for a in angles]
            hexes.append(ShapelyPolygon(coords))
            x += dx
        y += dy
        row += 1

    return gpd.GeoDataFrame(geometry=hexes, crs=crs)


def _place_legend(ax, handles=None, loc="lower right", style=None, **kwargs):
    """Place a legend and raise it above all map layers."""
    if style is None:
        style = LEGEND_STYLE_LIGHT
    kw = {**style, **kwargs}
    leg = ax.legend(handles=handles, loc=loc, **kw) if handles is not None \
        else ax.legend(loc=loc, **kw)
    leg.set_zorder(200)
    return leg


# ===========================================================================
# Step 1 — Buffer and context maps
# ===========================================================================

def step1_buffer_and_maps(proj: dict, gen_dir: Path, figures_dir: Path) -> tuple:
    """
    Buffer the project boundary by BUFFER_DIST_M metres and produce two
    context maps:
      1a — OpenStreetMap basemap
      1b — Esri WorldImagery satellite basemap (current)

    Returns boundary_wgs, buffer_wgs (both WGS84 GeoDataFrames).
    """
    print("\n" + "=" * 65)
    print("Step 1 — Buffer and context maps")
    print("=" * 65)

    # --- Load boundary and reproject to UTM for metric buffering ----------
    print(f"  Loading boundary: {proj['boundary_shp']}")
    boundary_wgs = gpd.read_file(proj["boundary_shp"]).to_crs("EPSG:4326")
    boundary_utm = boundary_wgs.to_crs(config.UTM_CRS)

    # Dissolve to a single polygon in case the shapefile has multiple features
    boundary_utm = boundary_utm.dissolve()
    boundary_wgs = boundary_utm.to_crs("EPSG:4326")

    # Buffer in UTM (distance in metres), then convert back to WGS84
    buffer_utm = boundary_utm.copy()
    buffer_utm["geometry"] = boundary_utm.buffer(config.BUFFER_DIST_M)
    buffer_wgs = buffer_utm.to_crs("EPSG:4326")

    # --- Save buffer polygon for downstream steps -------------------------
    out_path = gen_dir / "buffer_1km.gpkg"
    buffer_wgs.to_file(out_path, driver="GPKG")
    print(f"  Saved buffer: {out_path}")

    # Reproject to Web Mercator for contextily basemaps
    buffer_web   = buffer_wgs.to_crs(epsg=3857)
    boundary_web = boundary_wgs.to_crs(epsg=3857)
    xmin, ymin, xmax, ymax = buffer_web.total_bounds

    # --- Map helper: draws the two boundary overlays on an axis -----------
    def _add_overlays(ax):
        buffer_web.boundary.plot(ax=ax, color=BUFFER_COLOUR,   linewidth=2.5,
                                 linestyle="--", zorder=10)
        boundary_web.boundary.plot(ax=ax, color=BOUNDARY_COLOUR, linewidth=2.5,
                                   linestyle="-",  zorder=11)

    def _make_legend_handles():
        return [
            Line2D([0], [0], color=BOUNDARY_COLOUR, linewidth=2.5, linestyle="-",
                   label="Project boundary"),
            Line2D([0], [0], color=BUFFER_COLOUR,   linewidth=2.5, linestyle="--",
                   label="1 km buffer"),
        ]

    # --- Map 1a: OpenStreetMap basemap ------------------------------------
    print("  Producing OSM context map …")
    fig, ax = plt.subplots(figsize=(8, 8))
    ax.set_xlim(xmin, xmax)
    ax.set_ylim(ymin, ymax)
    ctx.add_basemap(ax, source=ctx.providers.OpenStreetMap.Mapnik, zoom="auto")
    _add_overlays(ax)
    _place_legend(ax, _make_legend_handles(), style=LEGEND_STYLE_LIGHT)
    ax.set_axis_off()
    fig.tight_layout()
    fname = figures_dir / f"{proj['project_name']}_01a_context_osm.png"
    fig.savefig(fname, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {fname.name}")

    # --- Map 1b: Satellite imagery basemap --------------------------------
    print("  Producing satellite context map …")
    fig, ax = plt.subplots(figsize=(8, 8))
    ax.set_xlim(xmin, xmax)
    ax.set_ylim(ymin, ymax)
    ctx.add_basemap(ax, source=ctx.providers.Esri.WorldImagery, zoom="auto")
    _add_overlays(ax)
    _place_legend(ax, _make_legend_handles(), style=LEGEND_STYLE_DARK)
    ax.set_axis_off()
    fig.tight_layout()
    fname = figures_dir / f"{proj['project_name']}_01b_context_satellite.png"
    fig.savefig(fname, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {fname.name}")

    return boundary_wgs, buffer_wgs


# ===========================================================================
# Step 2 — Plots within buffer
# ===========================================================================

def step2_plots(proj: dict, boundary_wgs: gpd.GeoDataFrame,
                buffer_wgs: gpd.GeoDataFrame,
                gen_dir: Path, figures_dir: Path) -> tuple:
    """
    Subset city parcels (plots) to the 1 km buffer area via intersection
    (plot shapes are NOT clipped — any plot that touches the buffer is kept
    in its original form).

    Adds three columns:
      in_project  : 1 if >= 50% of the plot's area falls inside the project
                    boundary, 0 otherwise.
      area_m2     : plot area in square metres (UTM).
      exclude_plot: 1 if the plot's area is above the PLOT_SIZE_UPPER_PERCENTILE
                    or below the PLOT_SIZE_LOWER_PERCENTILE of plots inside the
                    project boundary, 0 otherwise.

    Returns (plots_utm, p_upper, p_lower).
    """
    print("\n" + "=" * 65)
    print("Step 2 — Plots within buffer")
    print("=" * 65)

    # --- Intersect (not clip) to buffer -----------------------------------
    print(f"  Loading plots: {config.PLOTS_SHP}")
    plots_raw = gpd.read_file(config.PLOTS_SHP)
    print(f"  Selecting plots that intersect the 1 km buffer …")
    plots_crs   = plots_raw.crs or "EPSG:4326"
    buffer_poly = buffer_wgs.to_crs(plots_crs).union_all()
    plots = plots_raw[plots_raw.geometry.intersects(buffer_poly)].copy()
    print(f"  {len(plots):,} plots intersect the buffer (shapes unchanged)")

    # Reproject to UTM for area calculations
    plots_utm    = plots.to_crs(config.UTM_CRS)
    boundary_utm = boundary_wgs.to_crs(config.UTM_CRS)
    boundary_poly = boundary_utm.union_all()

    # --- in_project flag --------------------------------------------------
    print("  Computing in_project flags …")
    intersect_area = plots_utm.geometry.intersection(boundary_poly).area
    plot_area      = plots_utm.geometry.area
    overlap_frac   = np.where(plot_area > 0, intersect_area / plot_area, 0)
    plots_utm["in_project"] = (overlap_frac >= 0.5).astype(int)

    # --- Plot area (m²) column -------------------------------------------
    plots_utm["area_m2"] = plot_area

    # --- exclude_plot flag ------------------------------------------------
    # Thresholds computed using ONLY in-project plots; applied to all buffer plots.
    project_areas = plots_utm.loc[plots_utm["in_project"] == 1, "area_m2"]
    p_upper = np.percentile(project_areas, config.PLOT_SIZE_UPPER_PERCENTILE)
    p_lower = np.percentile(project_areas, config.PLOT_SIZE_LOWER_PERCENTILE)
    plots_utm["exclude_plot"] = (
        (plots_utm["area_m2"] > p_upper) | (plots_utm["area_m2"] < p_lower)
    ).astype(int)
    n_excl = plots_utm["exclude_plot"].sum()
    print(f"  Plot size thresholds: lower={p_lower:,.1f} m² "
          f"(p{config.PLOT_SIZE_LOWER_PERCENTILE}), "
          f"upper={p_upper:,.0f} m² (p{config.PLOT_SIZE_UPPER_PERCENTILE})")
    print(f"  Excluded plots flagged: {n_excl:,} "
          f"({100 * n_excl / len(plots_utm):.1f}% of buffer plots)")

    # --- Figure 2a: plot size distributions ------------------------------
    print("  Producing plot size distribution figure …")
    inside  = plots_utm.loc[plots_utm["in_project"] == 1, "area_m2"]
    outside = plots_utm.loc[plots_utm["in_project"] == 0, "area_m2"]

    log_inside  = np.log10(inside[inside   > 0])
    log_outside = np.log10(outside[outside > 0])

    fig, ax = plt.subplots(figsize=(7, 4))
    for data, label, colour in [
        (log_inside,  "Inside project",  "#1a6faf"),
        (log_outside, "Outside project", "#e07b39"),
    ]:
        kde = gaussian_kde(data, bw_method="scott")
        x   = np.linspace(data.min(), data.max(), 300)
        ax.fill_between(x, kde(x), alpha=0.35, color=colour)
        ax.plot(x, kde(x), color=colour, linewidth=1.5, label=label)

    ax.axvline(np.log10(p_upper), color="#333333", linewidth=1, linestyle=":",
               label=f"p{config.PLOT_SIZE_UPPER_PERCENTILE} upper ({p_upper:,.0f} m²)")
    ax.axvline(np.log10(p_lower), color="#888888", linewidth=1, linestyle=":",
               label=f"p{config.PLOT_SIZE_LOWER_PERCENTILE} lower ({p_lower:,.1f} m²)")
    ax.set_xlabel("Plot area (log₁₀ m²)")
    ax.set_ylabel("Density")
    ax.set_title("Distribution of plot sizes within 1 km buffer")
    _place_legend(ax, loc="upper left", bbox_to_anchor=(1.01, 1),
                  style=LEGEND_STYLE_LIGHT, borderaxespad=0)
    fig.tight_layout(rect=(0, 0, 0.78, 1))
    fname = figures_dir / f"{proj['project_name']}_02a_plot_size_distribution.png"
    fig.savefig(fname, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {fname.name}")

    # --- Figure 2b: plots map --------------------------------------------
    print("  Producing plots map …")
    buffer_web   = buffer_wgs.to_crs(epsg=3857)
    boundary_web = boundary_wgs.to_crs(epsg=3857)
    plots_web    = plots_utm.to_crs(epsg=3857)
    xmin, ymin, xmax, ymax = buffer_web.total_bounds

    fig, ax = plt.subplots(figsize=(9, 9))
    ax.set_xlim(xmin, xmax)
    ax.set_ylim(ymin, ymax)
    ctx.add_basemap(ax, source=ctx.providers.OpenStreetMap.Mapnik, zoom="auto")

    # Normal plots: thin black boundary, no fill
    normal = plots_web[plots_web["exclude_plot"] == 0]
    normal.plot(ax=ax, facecolor="none", edgecolor="black", linewidth=0.4, zorder=3)

    # Excluded plots: transparent fill, solid red hatch lines
    excluded = plots_web[plots_web["exclude_plot"] == 1]
    for geom in excluded.geometry:
        polys = [geom] if geom.geom_type == "Polygon" else list(geom.geoms)
        for poly in polys:
            patch = mpatches.Polygon(
                np.array(poly.exterior.coords),
                facecolor="none", edgecolor=HATCH_COLOUR,
                linewidth=0.8, hatch="///", zorder=4,
            )
            ax.add_patch(patch)

    # Boundary and buffer overlaid on top
    buffer_web.boundary.plot(ax=ax, color=BUFFER_COLOUR,   linewidth=2.5,
                             linestyle="--", zorder=10)
    boundary_web.boundary.plot(ax=ax, color=BOUNDARY_COLOUR, linewidth=2.5,
                               linestyle="-",  zorder=11)

    legend_handles = [
        Line2D([0], [0], color=BOUNDARY_COLOUR, linewidth=2.5, label="Project boundary"),
        Line2D([0], [0], color=BUFFER_COLOUR,   linewidth=2.5, linestyle="--",
               label="1 km buffer"),
        mpatches.Patch(facecolor="none", edgecolor="black", linewidth=0.8,
                       label="Plot boundary"),
        mpatches.Patch(facecolor="none", edgecolor=HATCH_COLOUR, linewidth=0.8,
                       hatch="///",
                       label=f"Excluded plot (< p{config.PLOT_SIZE_LOWER_PERCENTILE} "
                             f"or > p{config.PLOT_SIZE_UPPER_PERCENTILE})"),
    ]
    _place_legend(ax, legend_handles, style=LEGEND_STYLE_LIGHT)
    ax.set_axis_off()
    fig.tight_layout()
    fname = figures_dir / f"{proj['project_name']}_02b_plots_map.png"
    fig.savefig(fname, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {fname.name}")

    # --- Save to gen ------------------------------------------------------
    plots_out = plots_utm.to_crs("EPSG:4326")
    out_path  = gen_dir / "plots_buffer.gpkg"
    plots_out.to_file(out_path, driver="GPKG")
    print(f"  Saved: {out_path}")

    return plots_utm, p_upper, p_lower


# ===========================================================================
# Step 3 — Landuse within buffer
# ===========================================================================

def step3_landuse(proj: dict, boundary_wgs: gpd.GeoDataFrame,
                  buffer_wgs: gpd.GeoDataFrame,
                  gen_dir: Path, figures_dir: Path) -> gpd.GeoDataFrame:
    """
    Subset Masterplan 2020 landuse polygons to the 1 km buffer area.

    Adds one column:
      r2_zone: 1 if zone_code == 'R2', 0 otherwise.

    Produces a map showing all landuse polygons, each new_zoning value
    coloured distinctly. No cross-out of any zones.

    Returns landuse_utm (UTM CRS).
    """
    print("\n" + "=" * 65)
    print("Step 3 — Landuse within buffer")
    print("=" * 65)

    # --- Load and clip to buffer ------------------------------------------
    print(f"  Loading landuse: {config.LANDUSE_SHP}")
    landuse_raw = gpd.read_file(config.LANDUSE_SHP)
    print(f"  Clipping {len(landuse_raw):,} landuse polygons to 1 km buffer …")
    landuse = gpd.clip(landuse_raw, buffer_wgs).copy()
    print(f"  {len(landuse):,} polygons after clipping")

    # Reproject to UTM
    landuse_utm = landuse.to_crs(config.UTM_CRS)

    # --- r2_zone flag -----------------------------------------------------
    landuse_utm["r2_zone"] = (landuse_utm["zone_code"] == "R2").astype(int)
    n_r2     = landuse_utm["r2_zone"].sum()
    n_non_r2 = len(landuse_utm) - n_r2
    print(f"  R2 polygons  : {n_r2:,}")
    print(f"  Non-R2 polygons: {n_non_r2:,}")

    # --- Figure 3: landuse map -------------------------------------------
    print("  Producing landuse map …")
    buffer_web   = buffer_wgs.to_crs(epsg=3857)
    boundary_web = boundary_wgs.to_crs(epsg=3857)
    landuse_web  = landuse_utm.to_crs(epsg=3857)
    xmin, ymin, xmax, ymax = buffer_web.total_bounds

    # Unique colour per new_zoning value
    zone_types  = sorted(landuse_utm["new_zoning"].dropna().unique())
    palette     = plt.cm.get_cmap("tab20", max(len(zone_types), 1))
    zone_colour = {z: palette(i) for i, z in enumerate(zone_types)}

    fig, ax = plt.subplots(figsize=(10, 10))
    ax.set_xlim(xmin, xmax)
    ax.set_ylim(ymin, ymax)
    ctx.add_basemap(ax, source=ctx.providers.OpenStreetMap.Mapnik, zoom="auto")

    # Draw all polygons coloured by new_zoning
    for zone in zone_types:
        subset = landuse_web[landuse_web["new_zoning"] == zone]
        colour = zone_colour[zone]
        subset.plot(ax=ax, facecolor=colour, edgecolor="black",
                    linewidth=0.4, alpha=0.6, zorder=3)

    # Project boundary and buffer on top
    buffer_web.boundary.plot(ax=ax, color=BUFFER_COLOUR,   linewidth=2.5,
                             linestyle="--", zorder=10)
    boundary_web.boundary.plot(ax=ax, color=BOUNDARY_COLOUR, linewidth=2.5,
                               linestyle="-",  zorder=11)

    # Legend: structural elements + one entry per zone type
    legend_handles = [
        Line2D([0], [0], color=BOUNDARY_COLOUR, linewidth=2.5,
               label="Project boundary"),
        Line2D([0], [0], color=BUFFER_COLOUR,   linewidth=2.5, linestyle="--",
               label="1 km buffer"),
    ]
    for zone in zone_types:
        legend_handles.append(
            mpatches.Patch(facecolor=zone_colour[zone], edgecolor="black",
                           linewidth=0.4, alpha=0.7, label=zone)
        )
    _place_legend(ax, legend_handles,
                  loc="upper left", bbox_to_anchor=(1.01, 1),
                  style={**LEGEND_STYLE_LIGHT, "fontsize": 9},
                  ncol=1, borderaxespad=0)
    ax.set_axis_off()
    fname = figures_dir / f"{proj['project_name']}_03_landuse_map.png"
    fig.savefig(fname, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {fname.name}")

    # --- Save to gen ------------------------------------------------------
    landuse_out = landuse_utm.to_crs("EPSG:4326")
    out_path    = gen_dir / "landuse_buffer.gpkg"
    landuse_out.to_file(out_path, driver="GPKG")
    print(f"  Saved: {out_path}")

    return landuse_utm


# ===========================================================================
# Step 4 — Analysis mask
# ===========================================================================

def step4_mask(proj: dict, buffer_wgs: gpd.GeoDataFrame,
               plots_utm: gpd.GeoDataFrame, p_upper: float, p_lower: float,
               landuse_utm: gpd.GeoDataFrame,
               gen_dir: Path) -> gpd.GeoDataFrame:
    """
    Build a binary analysis mask by subtracting excluded areas from the buffer.

    Excluded areas:
      1. Footprints of plots outside the PLOT_SIZE_LOWER / UPPER percentile range.
      2. Areas covered by landuse zones where zone_code != 'R2'.

    Returns the mask as a GeoDataFrame (WGS84).
    """
    print("\n" + "=" * 65)
    print("Step 4 — Analysis mask")
    print("=" * 65)

    buffer_utm = buffer_wgs.to_crs(config.UTM_CRS)
    mask_poly  = buffer_utm.union_all()

    # --- Remove excluded-plot footprints ---------------------------------
    excl_plots = plots_utm[plots_utm["exclude_plot"] == 1]
    if len(excl_plots) > 0:
        excl_union = excl_plots.union_all()
        mask_poly  = mask_poly.difference(excl_union)
        print(f"  Subtracted {len(excl_plots):,} excluded-plot footprints")
    else:
        print("  No excluded plots to subtract")

    # --- Remove non-R2 landuse areas -------------------------------------
    non_r2 = landuse_utm[landuse_utm["r2_zone"] == 0]
    if len(non_r2) > 0:
        non_r2_union = non_r2.union_all()
        mask_poly    = mask_poly.difference(non_r2_union)
        print(f"  Subtracted {len(non_r2):,} non-R2 zoning polygons")
    else:
        print("  No non-R2 landuse polygons to subtract")

    # --- Save mask -------------------------------------------------------
    mask_utm = gpd.GeoDataFrame(geometry=[mask_poly], crs=config.UTM_CRS)
    mask_wgs = mask_utm.to_crs("EPSG:4326")
    out_path = gen_dir / "analysis_mask.gpkg"
    mask_wgs.to_file(out_path, driver="GPKG")
    print(f"  Saved: {out_path}")
    print(f"  Mask area: {mask_poly.area / 1e6:.3f} km²")

    return mask_wgs


# ===========================================================================
# Step 5 — Propensity scores from satellite embeddings
# ===========================================================================

def step5_propensity_scores(proj: dict, boundary_wgs: gpd.GeoDataFrame,
                             buffer_wgs: gpd.GeoDataFrame,
                             gen_dir: Path, temp_dir: Path,
                             figures_dir: Path) -> None:
    """
    Estimate a pixel-level propensity score for every pixel inside the 1 km
    buffer using a probit model.  The analysis mask is NOT applied — all
    pixels within the buffer footprint are used.

    Features:
      - All 64 Google satellite embedding bands (A00–A63)
      (Land use categories are intentionally excluded.)

    Outcome: whether the pixel falls inside the project boundary (0/1).

    Produces:
      - gen/propensity_scores.tif
      - figures/{project}_05a_propensity_map.png
      - figures/{project}_05b_propensity_distribution.png
    """
    print("\n" + "=" * 65)
    print("Step 5 — Propensity scores from satellite embeddings")
    print("=" * 65)

    # -----------------------------------------------------------------------
    # 5a — Load satellite embedding raster and apply analysis mask
    # -----------------------------------------------------------------------
    year = proj["satembed_year"]
    tif_candidates = sorted(config.SATEMBED_DIR.glob(f"*_ANNUAL_{year}_*.tif"))
    if not tif_candidates:
        raise FileNotFoundError(
            f"No satembed GeoTIFF found for year {year} in {config.SATEMBED_DIR}. "
            f"Pattern searched: *_ANNUAL_{year}_*.tif"
        )
    satembed_path = tif_candidates[0]
    print(f"  Satembed raster: {satembed_path.name}")

    with rasterio.open(satembed_path) as src:
        raster_crs       = src.crs
        raster_meta      = src.meta.copy()
        raster_transform = src.transform
        raster_shape     = (src.height, src.width)
        n_bands          = src.count
        print(f"  Raster: {src.width}×{src.height} px, {n_bands} bands, CRS={raster_crs}")

        # Clip to buffer extent so we don't process the full global raster
        buffer_raster_crs = buffer_wgs.to_crs(raster_crs)
        buffer_shapes     = [mapping(geom) for geom in buffer_raster_crs.geometry]

        satembed_data, _ = rasterio.mask.mask(
            src, buffer_shapes, crop=False, nodata=np.nan, filled=True,
        )

    print("  Loaded satembed data clipped to buffer extent")

    # -----------------------------------------------------------------------
    # 5b — Build per-pixel DataFrame
    # -----------------------------------------------------------------------

    # Rasterize project boundary → in_project band
    boundary_raster_crs = boundary_wgs.to_crs(raster_crs)
    boundary_shapes = [(mapping(geom), 1)
                       for geom in boundary_raster_crs.geometry]
    in_project_band = rasterio.features.rasterize(
        boundary_shapes,
        out_shape=raster_shape,
        transform=raster_transform,
        fill=0,
        dtype="uint8",
    ).astype(float)

    # Valid pixels: those where the first satembed band is not NaN
    valid_mask = ~np.isnan(satembed_data[0])
    n_valid = valid_mask.sum()
    print(f"  Valid pixels for analysis: {n_valid:,}")

    # Flatten all bands to 1D arrays for valid pixels only
    flat_idx = np.argwhere(valid_mask)
    rows_idx, cols_idx = flat_idx[:, 0], flat_idx[:, 1]

    band_names = [f"A{i:02d}" for i in range(n_bands)]
    pixel_df = pd.DataFrame(
        {name: satembed_data[i][rows_idx, cols_idx] for i, name in enumerate(band_names)}
    )
    pixel_df["in_project"] = in_project_band[rows_idx, cols_idx].astype(int)
    pixel_df["row"]        = rows_idx
    pixel_df["col"]        = cols_idx

    print(f"  Pixels inside project  : {pixel_df['in_project'].sum():,}")
    print(f"  Pixels outside project : {(pixel_df['in_project'] == 0).sum():,}")

    # -----------------------------------------------------------------------
    # 5c — Probit model (satellite embeddings only)
    # -----------------------------------------------------------------------
    print("  Fitting probit model …")

    X = pixel_df[band_names].astype(float)
    y = pixel_df["in_project"].astype(float)

    X_const = sm.add_constant(X)

    model  = sm.Probit(y, X_const)
    result = model.fit(maxiter=100, disp=False)
    print(result.summary())

    pixel_df["propensity_score"] = result.predict(X_const)

    # -----------------------------------------------------------------------
    # 5d — Write propensity score raster
    # -----------------------------------------------------------------------
    score_raster = np.full(raster_shape, np.nan, dtype=np.float32)
    score_raster[rows_idx, cols_idx] = pixel_df["propensity_score"].values

    score_meta = raster_meta.copy()
    score_meta.update({"count": 1, "dtype": "float32", "nodata": np.nan})

    score_tif_path = gen_dir / "propensity_scores.tif"
    with rasterio.open(score_tif_path, "w", **score_meta) as dst:
        dst.write(score_raster, 1)
    print(f"  Saved propensity score raster: {score_tif_path}")

    # --- Figure 5a: propensity score map ---------------------------------
    print("  Producing propensity score map …")
    buffer_web   = buffer_wgs.to_crs(epsg=3857)
    boundary_web = boundary_wgs.to_crs(epsg=3857)
    xmin_w, ymin_w, xmax_w, ymax_w = buffer_web.total_bounds

    score_web_path = temp_dir / "propensity_scores_web.tif"
    with rasterio.open(score_tif_path) as src:
        dst_crs = rasterio.CRS.from_epsg(3857)
        dst_transform, dst_width, dst_height = rasterio.warp.calculate_default_transform(
            src.crs, dst_crs, src.width, src.height, *src.bounds
        )
        kwargs = src.meta.copy()
        kwargs.update({
            "crs":       dst_crs,
            "transform": dst_transform,
            "width":     dst_width,
            "height":    dst_height,
        })
        with rasterio.open(score_web_path, "w", **kwargs) as dst:
            rasterio.warp.reproject(
                source=rasterio.band(src, 1),
                destination=rasterio.band(dst, 1),
                src_transform=src.transform,
                src_crs=src.crs,
                dst_transform=dst_transform,
                dst_crs=dst_crs,
                resampling=rasterio.warp.Resampling.bilinear,
            )

    with rasterio.open(score_web_path) as src:
        score_web = src.read(1)
        extent    = [src.bounds.left, src.bounds.right,
                     src.bounds.bottom, src.bounds.top]

    fig, ax = plt.subplots(figsize=(9, 9))
    ax.set_xlim(xmin_w, xmax_w)
    ax.set_ylim(ymin_w, ymax_w)
    ctx.add_basemap(ax, source=ctx.providers.OpenStreetMap.Mapnik, zoom="auto")

    score_display = np.where(np.isnan(score_web), np.nan, score_web)
    im = ax.imshow(
        score_display, cmap="viridis", vmin=0, vmax=1,
        extent=extent, origin="upper", zorder=5, alpha=0.75,
    )
    fig.colorbar(im, ax=ax, fraction=0.03, pad=0.01, label="Propensity score")

    buffer_web.boundary.plot(ax=ax, color=BUFFER_COLOUR, linewidth=2.5,
                             linestyle="--", zorder=10)
    boundary_web.boundary.plot(ax=ax, color=BOUNDARY_COLOUR, linewidth=2.5,
                               linestyle="-", zorder=11)
    legend_handles = [
        Line2D([0], [0], color=BOUNDARY_COLOUR, linewidth=2.5,
               label="Project boundary"),
        Line2D([0], [0], color=BUFFER_COLOUR, linewidth=2.5, linestyle="--",
               label="1 km buffer"),
    ]
    _place_legend(ax, legend_handles, style=LEGEND_STYLE_LIGHT)
    ax.set_axis_off()
    fig.tight_layout()
    fname = figures_dir / f"{proj['project_name']}_05a_propensity_map.png"
    fig.savefig(fname, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {fname.name}")

    # --- Figure 5b: propensity score distributions -----------------------
    print("  Producing propensity score distribution figure …")
    scores_in  = pixel_df.loc[pixel_df["in_project"] == 1, "propensity_score"]
    scores_out = pixel_df.loc[pixel_df["in_project"] == 0, "propensity_score"]

    fig, ax = plt.subplots(figsize=(7, 4))
    for scores, label, colour in [
        (scores_in,  "Inside project",  "#1a6faf"),
        (scores_out, "Outside project", "#e07b39"),
    ]:
        kde = gaussian_kde(scores, bw_method="scott")
        x   = np.linspace(0, 1, 300)
        ax.fill_between(x, kde(x), alpha=0.35, color=colour)
        ax.plot(x, kde(x), color=colour, linewidth=1.5, label=label)

    ax.set_xlabel("Propensity score")
    ax.set_ylabel("Density")
    ax.set_title("Distribution of propensity scores (probit model, satembeds only)")
    _place_legend(ax, loc="upper left", bbox_to_anchor=(1.01, 1),
                  style=LEGEND_STYLE_LIGHT, borderaxespad=0)
    fig.tight_layout(rect=(0, 0, 0.78, 1))
    fname = figures_dir / f"{proj['project_name']}_05b_propensity_distribution.png"
    fig.savefig(fname, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {fname.name}")


# ===========================================================================
# Step 6 — Sample frame
# ===========================================================================

def step6_sample_frame(proj: dict, boundary_wgs: gpd.GeoDataFrame,
                       buffer_wgs: gpd.GeoDataFrame,
                       plots_utm: gpd.GeoDataFrame, p_upper: float,
                       landuse_utm: gpd.GeoDataFrame,
                       gen_dir: Path, figures_dir: Path) -> gpd.GeoDataFrame:
    """
    Build the sample frame as a filtered hexagonal grid.

    Pipeline:
      1. Generate hex grid covering the buffer (HEX_SIZE_M circumradius).
      2. Keep hexagons whose centroid lies inside the buffer polygon.
      3. Drop hexagons whose centroid falls inside a plot above the upper
         size percentile (likely non-residential large parcels).
      4. Restrict to hexagons whose centroid falls inside R1/R2 zoning,
         after a morphological close (20 m out, 20 m in) to fill road gaps.
      5. Annotate: in_project flag and signed distance to project boundary.

    Produces:
      - gen/sample_frame.gpkg
      - figures/{project}_06a_sample_frame_map.png
      - figures/{project}_06b_distance_histogram.png

    Returns the sample frame GeoDataFrame (UTM CRS).
    """
    print("\n" + "=" * 65)
    print("Step 6 — Sample frame")
    print("=" * 65)

    boundary_utm = boundary_wgs.to_crs(config.UTM_CRS)
    buffer_utm   = buffer_wgs.to_crs(config.UTM_CRS)
    boundary_poly = boundary_utm.union_all()
    buffer_poly   = buffer_utm.union_all()

    # -----------------------------------------------------------------------
    # 6a — Hexagonal grid clipped to buffer
    # -----------------------------------------------------------------------
    print(f"  Generating hex grid (circumradius {config.HEX_SIZE_M} m) …")
    hexgrid = _make_hex_grid(tuple(buffer_utm.total_bounds), config.HEX_SIZE_M, config.UTM_CRS)
    hexgrid = hexgrid[hexgrid.centroid.intersects(buffer_poly)].copy().reset_index(drop=True)
    print(f"  {len(hexgrid):,} hexagons cover the buffer")

    # -----------------------------------------------------------------------
    # 6b — Remove hexagons with centroid inside a large plot
    # -----------------------------------------------------------------------
    large_plots = plots_utm[plots_utm["area_m2"] > p_upper]
    if len(large_plots) > 0:
        large_union = large_plots.union_all()
        mask_large  = hexgrid.centroid.within(large_union)
        hexgrid     = hexgrid[~mask_large].copy().reset_index(drop=True)
        print(f"  Removed {mask_large.sum():,} hexagons inside large plots "
              f"({len(hexgrid):,} remaining)")
    else:
        print("  No large plots to exclude")

    # -----------------------------------------------------------------------
    # 6c — Residential landuse layer (morphological closing)
    # -----------------------------------------------------------------------
    print("  Building residential landuse layer (R1 + R2, 20 m close) …")
    residential   = landuse_utm[landuse_utm["zone_code"].isin(["R1", "R2"])]
    if len(residential) == 0:
        raise ValueError("No R1 or R2 polygons found in landuse layer.")
    residential_closed = residential.union_all().buffer(20).buffer(-20)
    print(f"  Residential area after closing: "
          f"{residential_closed.area / 1e6:.3f} km²")

    # -----------------------------------------------------------------------
    # 6d — Filter to residential area → sample frame
    # -----------------------------------------------------------------------
    mask_res = hexgrid.centroid.within(residential_closed)
    hexgrid  = hexgrid[mask_res].copy().reset_index(drop=True)
    print(f"  {len(hexgrid):,} hexagons in sample frame after residential filter")

    # -----------------------------------------------------------------------
    # 6e — in_project flag and signed distance to boundary
    # -----------------------------------------------------------------------
    boundary_line = boundary_poly.boundary
    centroids     = hexgrid.centroid

    hexgrid["in_project"]      = centroids.within(boundary_poly).astype(int)
    raw_dist                   = centroids.distance(boundary_line)
    hexgrid["dist_to_boundary"] = np.where(
        hexgrid["in_project"] == 1, -raw_dist, raw_dist
    )

    n_inside  = hexgrid["in_project"].sum()
    n_outside = len(hexgrid) - n_inside
    print(f"  Inside project boundary : {n_inside:,}")
    print(f"  Outside project boundary: {n_outside:,}")

    # -----------------------------------------------------------------------
    # 6f — Save sample frame
    # -----------------------------------------------------------------------
    sample_wgs = hexgrid.to_crs("EPSG:4326")
    out_path   = gen_dir / "sample_frame.gpkg"
    sample_wgs.to_file(out_path, driver="GPKG")
    print(f"  Saved: {out_path}")

    # -----------------------------------------------------------------------
    # 6g — Figure 06a: sample frame map
    # -----------------------------------------------------------------------
    print("  Producing sample frame map …")
    buffer_web   = buffer_wgs.to_crs(epsg=3857)
    boundary_web = boundary_wgs.to_crs(epsg=3857)
    hexgrid_web  = hexgrid.to_crs(epsg=3857)
    xmin, ymin, xmax, ymax = buffer_web.total_bounds

    fig, ax = plt.subplots(figsize=(10, 10))
    ax.set_xlim(xmin, xmax)
    ax.set_ylim(ymin, ymax)
    ctx.add_basemap(ax, source=ctx.providers.OpenStreetMap.Mapnik, zoom="auto")

    hexgrid_web.plot(ax=ax, facecolor="none", edgecolor="black",
                     linewidth=0.4, zorder=3)

    buffer_web.boundary.plot(ax=ax, color=BUFFER_COLOUR, linewidth=2.5,
                             linestyle="--", zorder=10)
    boundary_web.boundary.plot(ax=ax, color=BOUNDARY_COLOUR, linewidth=2.5,
                               linestyle="-", zorder=11)

    legend_handles = [
        Line2D([0], [0], color=BOUNDARY_COLOUR, linewidth=2.5,
               label="Project boundary"),
        Line2D([0], [0], color=BUFFER_COLOUR, linewidth=2.5, linestyle="--",
               label="1 km buffer"),
        mpatches.Patch(facecolor="none", edgecolor="black", linewidth=0.8,
                       label=f"Sample hexagon ({config.HEX_SIZE_M} m)"),
    ]
    _place_legend(ax, legend_handles, style=LEGEND_STYLE_LIGHT)
    ax.set_axis_off()
    fig.tight_layout()
    fname = figures_dir / f"{proj['project_name']}_06a_sample_frame_map.png"
    fig.savefig(fname, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {fname.name}")

    # -----------------------------------------------------------------------
    # 6h — Figure 06b: distance histogram
    # -----------------------------------------------------------------------
    print("  Producing distance histogram …")
    dists = np.asarray(hexgrid["dist_to_boundary"], dtype=float)

    # Bin edges snapped to 100 m
    bin_min = np.floor(dists.min() / 100) * 100
    bin_max = np.ceil(dists.max()  / 100) * 100
    bin_edges = np.arange(bin_min, bin_max + 100, 100)

    fig, ax = plt.subplots(figsize=(9, 4))

    # Inside bars (dist ≤ 0)
    inside_dists  = dists[dists <= 0]
    outside_dists = dists[dists >  0]
    ax.hist(inside_dists,  bins=bin_edges, color=BOUNDARY_COLOUR,
            alpha=0.8, label="Inside project boundary")
    ax.hist(outside_dists, bins=bin_edges, color="#e07b39",
            alpha=0.8, label="Outside project boundary")

    ax.axvline(0, color="#333333", linewidth=1.2, linestyle="--",
               label="Project boundary (0 m)")
    ax.set_xlabel("Distance to project boundary (m)  —  negative = inside")
    ax.set_ylabel("Number of hexagons")
    ax.set_title("Sample frame: distance to project boundary")

    _place_legend(ax, loc="upper left", bbox_to_anchor=(1.01, 1),
                  style=LEGEND_STYLE_LIGHT, borderaxespad=0)
    fig.tight_layout(rect=(0, 0, 0.78, 1))
    fname = figures_dir / f"{proj['project_name']}_06b_distance_histogram.png"
    fig.savefig(fname, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {fname.name}")

    return hexgrid


# ===========================================================================
# Main
# ===========================================================================

def main():
    # --- Load project config and resolve output paths --------------------
    proj = config.get_project_config()
    pname = proj["project_name"]

    gen_dir     = config.GEN_DIR     / pname
    temp_dir    = config.TEMP_DIR    / pname
    figures_dir = config.FIGURES_DIR

    for d in [gen_dir, temp_dir, figures_dir]:
        d.mkdir(parents=True, exist_ok=True)

    print(f"\n{'=' * 65}")
    print(f"  Sample frame pipeline — project: {pname}")
    print(f"{'=' * 65}")
    print(f"  Source  : {config.SOURCE_DIR}")
    print(f"  Gen     : {gen_dir}")
    print(f"  Temp    : {temp_dir}")
    print(f"  Figures : {figures_dir}")

    # --- Run pipeline -----------------------------------------------------
    boundary_wgs, buffer_wgs = step1_buffer_and_maps(
        proj, gen_dir, figures_dir
    )

    plots_utm, p_upper, p_lower = step2_plots(
        proj, boundary_wgs, buffer_wgs, gen_dir, figures_dir
    )

    landuse_utm = step3_landuse(
        proj, boundary_wgs, buffer_wgs, gen_dir, figures_dir
    )

    step4_mask(
        proj, buffer_wgs, plots_utm, p_upper, p_lower,
        landuse_utm, gen_dir
    )

    step5_propensity_scores(
        proj, boundary_wgs, buffer_wgs,
        gen_dir, temp_dir, figures_dir
    )

    step6_sample_frame(
        proj, boundary_wgs, buffer_wgs, plots_utm, p_upper,
        landuse_utm, gen_dir, figures_dir
    )

    # --- Clean up temp directory on success ------------------------------
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
        print(f"\n  Temp directory cleaned up: {temp_dir}")

    print(f"\n{'=' * 65}")
    print("  Pipeline complete.")
    print(f"{'=' * 65}\n")


if __name__ == "__main__":
    main()
