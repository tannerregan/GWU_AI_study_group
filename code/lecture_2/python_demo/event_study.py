"""
Event study and spatial gradient analyses for satellite embedding outcomes.

Workflow
--------
  Step 1 — Load Google satellite embeddings for all available years and build
            a pixel-year panel, masked to the sample frame hexagons.
  Step 2 — Compute the treatment indicator (inside project boundary) and the
            signed distance to the project boundary for each pixel.
  Step 3 — DiD event study: for each of 64 embedding bands, regress pixel
            values on treatment × year interactions (pixel + year FEs, SEs
            clustered by 100 m distance bin). Plot coefficients with 95% CIs,
            using 2020 as the baseline year.
  Step 4 — Spatial gradient: for each band, regress pixel values on distance
            bin × year interactions (pixel FE, SEs clustered by distance bin).
            Plot coefficient lines by year with a colour gradient from the
            earliest to the latest year.

Usage
-----
  conda activate kigali_rehousing
  python code/01_prepare_sample_frame/event_study.py

Output
------
  output/figures/event_study/mpazi_event_study_band{N:02d}.png        (64 figs)
  output/figures/spatial_gradient/mpazi_spatial_gradient_band{N:02d}.png  (64 figs)

No data files are written.
"""

import re
from pathlib import Path

import geopandas as gpd
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np
import pandas as pd
import rasterio
import rasterio.mask
import rasterio.transform
from linearmodels import PanelOLS
import statsmodels.api as sm

import config

# ---------------------------------------------------------------------------
# Figure style — translated from Kieran Healy's socviz.co style guide.
# Kept consistent with prepare_sample_frame.py.
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

BOUNDARY_COLOUR = "#1a6faf"   # project boundary blue (matches prepare_sample_frame.py)
BASELINE_YEAR   = 2020        # DiD reference year

# Year colour ramp for spatial gradient (two-segment):
#   2017 → 2020 : red → light gray
#   2020 → 2025 : light gray → blue
YEAR_COLOUR_PRE  = "#c0392b"   # 2017  (red)
YEAR_COLOUR_BASE = "#bbbbbb"   # 2020  (light gray)
YEAR_COLOUR_POST = "#1a6faf"   # 2025  (blue)


# ===========================================================================
# Step 1 — Load satembeds and build a pixel-year panel
# ===========================================================================

def step1_load_panel(proj: dict) -> pd.DataFrame:
    """
    For every annual satembed GeoTIFF, mask out pixels that lie outside the
    sample frame hexagons, then stack all years into a long panel DataFrame.

    Returns
    -------
    DataFrame with columns:
      pixel_id  — integer pixel index (stable across years)
      year      — calendar year
      x_utm, y_utm — pixel centroid coordinates in the raster CRS
      band_00 … band_63 — 64 float32 embedding values
    """
    print("\n" + "=" * 65)
    print("Step 1 — Load satembeds and build pixel-year panel")
    print("=" * 65)

    sample_frame_path = config.GEN_DIR / proj["project_name"] / "sample_frame.gpkg"

    # --- Find satembed tifs and parse years --------------------------------
    tif_paths = sorted(
        config.SATEMBED_DIR.glob(
            f"GOOGLE_SATELLITE_EMBEDDING_V1_ANNUAL_*_{proj['project_name']}_*.tif"
        )
    )
    if not tif_paths:
        raise FileNotFoundError(
            f"No satembed tifs found in {config.SATEMBED_DIR}. "
            f"Expected files matching: GOOGLE_SATELLITE_EMBEDDING_V1_ANNUAL_*_{proj['project_name']}_*.tif"
        )

    year_tif = {}
    for p in tif_paths:
        m = re.search(r"ANNUAL_(\d{4})_", p.name)
        if m:
            year_tif[int(m.group(1))] = p

    print(f"  Found years: {sorted(year_tif)}")

    # --- Dissolve sample frame hexagons to a single masking polygon ---------
    print(f"  Loading sample frame: {sample_frame_path}")
    sf = gpd.read_file(sample_frame_path)

    with rasterio.open(tif_paths[0]) as src:
        raster_crs = src.crs

    # Reproject hexagons to the raster's CRS for masking
    hex_union = sf.to_crs(raster_crs).dissolve().geometry.iloc[0]
    print(f"  Hex union computed (raster CRS: {raster_crs})")

    # --- Identify valid pixels from the first year -------------------------
    # All years share the same spatial grid, so we need only one pass to find
    # which pixels fall inside the hex union.
    first_year = sorted(year_tif)[0]
    with rasterio.open(year_tif[first_year]) as src:
        masked_data, masked_transform = rasterio.mask.mask(
            src, [hex_union], crop=True, nodata=np.nan, all_touched=False
        )
        n_bands, height, width = masked_data.shape

        # A pixel is valid if it is non-NaN in every band
        valid_2d = np.all(np.isfinite(masked_data), axis=0)   # (H, W) bool
        valid_rows, valid_cols = np.where(valid_2d)

        # Pixel centroid coordinates in the raster CRS
        xs, ys = rasterio.transform.xy(masked_transform, valid_rows, valid_cols)
        xs = np.asarray(xs, dtype=np.float64)
        ys = np.asarray(ys, dtype=np.float64)

    n_pixels = len(valid_rows)
    pixel_ids = np.arange(n_pixels)
    band_cols = [f"band_{i:02d}" for i in range(n_bands)]
    print(f"  Valid pixels in sample frame: {n_pixels:,}")

    # --- Load one year at a time and append to the panel -------------------
    frames = []
    for year in sorted(year_tif):
        print(f"    Loading {year} …", end="  ")
        with rasterio.open(year_tif[year]) as src:
            yr_data, _ = rasterio.mask.mask(
                src, [hex_union], crop=True, nodata=np.nan, all_touched=False
            )
        # Extract only the valid pixels: shape → (n_bands, n_valid)
        values = yr_data[:, valid_rows, valid_cols]   # (64, n_valid)
        yr_df = pd.DataFrame(values.T, columns=band_cols)
        yr_df.insert(0, "pixel_id", pixel_ids)
        yr_df.insert(1, "year", year)
        yr_df.insert(2, "x_utm", xs)
        yr_df.insert(3, "y_utm", ys)
        frames.append(yr_df)
        print(f"done  ({yr_df.shape[0]:,} rows)")

    panel = pd.concat(frames, ignore_index=True)
    print(f"  Panel: {panel.shape[0]:,} rows × {panel.shape[1]} columns")
    return panel


# ===========================================================================
# Step 2 — Add treatment indicator and signed distance
# ===========================================================================

def step2_add_treatment(panel: pd.DataFrame, proj: dict) -> pd.DataFrame:
    """
    For each unique pixel centroid compute (once; these are time-invariant):
      in_project — 1 if the pixel centroid falls inside the project boundary
      dist_m     — signed distance to the boundary exterior (negative = inside)
      dist_bin   — dist_m rounded to the nearest 100 m

    Returns the panel with three new columns.
    """
    print("\n" + "=" * 65)
    print("Step 2 — Add treatment indicator and signed distance")
    print("=" * 65)

    # --- Reproject boundary to UTM for metric distance calculations --------
    # Pixel coordinates stored in the panel are in the raster CRS, which may
    # be geographic (degrees). We always compute distances in UTM (metres).
    print(f"  Loading project boundary: {proj['boundary_shp']}")
    boundary_utm = (
        gpd.read_file(proj["boundary_shp"])
        .dissolve()
        .to_crs(config.UTM_CRS)
    )
    # Reproject pixel centroids from raster CRS to UTM
    tif_paths = sorted(
        config.SATEMBED_DIR.glob(
            f"GOOGLE_SATELLITE_EMBEDDING_V1_ANNUAL_*_{proj['project_name']}_*.tif"
        )
    )
    with rasterio.open(tif_paths[0]) as src:
        raster_crs = src.crs

    pixels = panel[["pixel_id", "x_utm", "y_utm"]].drop_duplicates("pixel_id")
    pixel_gdf = gpd.GeoDataFrame(
        {"pixel_id": pixels["pixel_id"].values},
        geometry=gpd.points_from_xy(pixels["x_utm"], pixels["y_utm"]),
        crs=raster_crs,
    ).to_crs(config.UTM_CRS)

    n_pixels = len(pixel_gdf)
    print(f"  Computing signed distance for {n_pixels:,} pixels …")

    # Use geopandas vector operations — avoids raw shapely scalar calls.
    # union_all() returns a single well-typed geometry from the dissolved GDF.
    boundary_geom = boundary_utm.union_all()           # dissolved project polygon
    boundary_ring  = boundary_utm.boundary.union_all() # exterior ring (LinearRing)

    # Distance from each pixel centroid to the boundary exterior (always ≥ 0)
    dists  = pixel_gdf.geometry.distance(boundary_ring).to_numpy()
    inside = pixel_gdf.geometry.within(boundary_geom).to_numpy()   # bool array
    signed_dist = np.where(inside, -dists, dists)
    in_project  = inside.astype(np.int8)

    # Round to nearest 100 m for binning
    dist_bin = (np.round(signed_dist / 100) * 100).astype(int)

    treat_df = pd.DataFrame({
        "pixel_id":   pixel_gdf["pixel_id"].values,
        "in_project": in_project,
        "dist_m":     signed_dist,
        "dist_bin":   dist_bin,
    })

    n_inside = int(in_project.sum())
    print(f"  Pixels inside boundary: {n_inside:,} / {n_pixels:,} "
          f"({100 * n_inside / n_pixels:.1f} %)")
    print(f"  Distance range: {signed_dist.min():.0f} m  to  {signed_dist.max():.0f} m")
    print(f"  Distance bins ({len(np.unique(dist_bin))}): {sorted(np.unique(dist_bin))}")

    return panel.merge(treat_df, on="pixel_id", how="left")


# ===========================================================================
# Propensity score computation
# ===========================================================================

def compute_propensity_scores(panel: pd.DataFrame) -> pd.DataFrame:
    """
    Fit a probit model on 2020 pixels (outcome = in_project, features = all 64
    satembed bands) and apply it to every year to produce a 'pscore' column.

    This replicates the Step 5 specification from prepare_sample_frame.py:
      Probit(in_project ~ band_00 + ... + band_63)
    fitted on the baseline year only, so the score captures which pixels
    looked like project-area pixels in 2020 satellite imagery.
    """
    print("\n" + "=" * 65)
    print("Propensity scores — fit 2020 probit, apply to all years")
    print("=" * 65)

    band_cols = [f"band_{i:02d}" for i in range(64)]
    data_2020 = panel[panel["year"] == BASELINE_YEAR]

    X_2020 = sm.add_constant(data_2020[band_cols].astype(float))
    y_2020 = data_2020["in_project"].astype(float)

    print(f"  Fitting probit on {len(data_2020):,} pixels from {BASELINE_YEAR} …")
    probit_res = sm.Probit(y_2020, X_2020).fit(maxiter=100, disp=False)
    print(f"  Converged: {probit_res.mle_retvals['converged']}")

    # Apply the 2020 model weights to every year's satembed values
    X_all = sm.add_constant(panel[band_cols].astype(float))
    panel = panel.copy()
    panel["pscore"] = probit_res.predict(X_all)
    print(f"  Propensity score range: "
          f"{panel['pscore'].min():.3f} – {panel['pscore'].max():.3f}")
    return panel


# ===========================================================================
# Step 3 — DiD event study (64 figures)
# ===========================================================================

def step3_event_study(panel: pd.DataFrame, figures_dir: Path, proj_name: str) -> None:
    """
    For each of 64 satembed bands estimate the two-way FE event study:

        Y_it = alpha_i (pixel FE) + gamma_t (year FE)
               + sum_{t != 2020} beta_t * (in_project_i x I[year=t]) + eps_it

    Standard errors are clustered by 100 m distance bin.  Plot beta_t with
    95 % CI for all years, with 2020 constrained to zero.
    """
    print("\n" + "=" * 65)
    print("Step 3 — DiD event study (64 bands)")
    print("=" * 65)

    out_dir = figures_dir / "event_study"
    out_dir.mkdir(parents=True, exist_ok=True)

    years = sorted(panel["year"].unique())
    non_baseline = [y for y in years if y != BASELINE_YEAR]

    # Set the (entity, time) MultiIndex required by linearmodels
    panel_idx = panel.set_index(["pixel_id", "year"]).sort_index()
    yr_idx = panel_idx.index.get_level_values("year")
    clusters = panel_idx["dist_bin"]

    band_cols = [f"band_{i:02d}" for i in range(64)]

    for b, band_col in enumerate(band_cols):
        print(f"  Band {b:02d} …", end="  ")

        # Build regressors: in_project × I[year = t] for each non-baseline year.
        # Control pixels contribute 0 to every column; treated pixels contribute
        # 1 only in the column matching their year.
        X = pd.DataFrame(
            {f"treat_{yr}": (panel_idx["in_project"] * (yr_idx == yr)).astype(float)
             for yr in non_baseline},
            index=panel_idx.index,
        )

        y = panel_idx[band_col]

        try:
            res = PanelOLS(y, X, entity_effects=True, time_effects=True).fit(
                cov_type="clustered", clusters=clusters  # type: ignore[arg-type]
            )
        except Exception as exc:
            print(f"WARN: regression failed ({exc}); skipping.")
            continue

        # Extract point estimates and 95 % CI (1.96 × SE)
        coefs = res.params
        ses   = res.std_errors
        ci_lo = coefs - 1.96 * ses
        ci_hi = coefs + 1.96 * ses

        # Assemble all years: insert the baseline (beta = 0, no CI) explicitly
        yr_coef  = {yr: coefs.get(f"treat_{yr}", np.nan) for yr in non_baseline}
        yr_lo    = {yr: ci_lo.get(f"treat_{yr}", np.nan)  for yr in non_baseline}
        yr_hi    = {yr: ci_hi.get(f"treat_{yr}", np.nan)  for yr in non_baseline}
        yr_coef[BASELINE_YEAR] = 0.0
        yr_lo[BASELINE_YEAR]   = np.nan     # no CI bar at baseline
        yr_hi[BASELINE_YEAR]   = np.nan

        # --- Plot ---
        fig, ax = plt.subplots(figsize=(8, 5))

        ax.axhline(0, color="#888888", linewidth=0.8, linestyle="--", zorder=1)
        ax.axvline(BASELINE_YEAR, color="#bbbbbb", linewidth=0.8,
                   linestyle=":", zorder=1)

        # Connect all points with a thin line
        ax.plot(years,
                [yr_coef[y] for y in years],
                "-", color=BOUNDARY_COLOUR, linewidth=1.0, alpha=0.5, zorder=2)

        # Non-baseline: coloured points + error bars
        nb_c  = [yr_coef[y] for y in non_baseline]
        nb_lo = [yr_coef[y] - yr_lo[y] for y in non_baseline]
        nb_hi = [yr_hi[y] - yr_coef[y] for y in non_baseline]
        ax.errorbar(
            non_baseline, nb_c,
            yerr=[nb_lo, nb_hi],
            fmt="o", color=BOUNDARY_COLOUR,
            markersize=6, capsize=4,
            linewidth=1.5, elinewidth=1.5, zorder=3,
        )
    

        # Baseline: solid black dot at zero
        ax.plot(BASELINE_YEAR, 0, "o", color="#333333", markersize=6, zorder=4)

        ax.set_xticks(years)
        ax.set_xlabel("Year")
        ax.set_ylabel("Coefficient (relative to 2020)")
        ax.set_title(
            f"Band {b:02d}  —  DiD event study  (baseline: {BASELINE_YEAR})",
            fontsize=12, pad=10,
        )

        fig.tight_layout()
        fname = out_dir / f"{proj_name}_event_study_band{b:02d}.png"
        fig.savefig(fname, bbox_inches="tight")
        plt.close(fig)
        print(f"saved")

    print(f"\n  64 event study figures → {out_dir}")

    # --- Propensity score event study (one extra figure) ------------------
    print("  Propensity score event study …", end="  ")
    y_ps = panel_idx["pscore"]
    X_ps = pd.DataFrame(
        {f"treat_{yr}": (panel_idx["in_project"] * (yr_idx == yr)).astype(float)
         for yr in non_baseline},
        index=panel_idx.index,
    )
    try:
        res_ps = PanelOLS(y_ps, X_ps, entity_effects=True, time_effects=True).fit(
            cov_type="clustered", clusters=clusters  # type: ignore[arg-type]
        )
        coefs_ps = res_ps.params
        ses_ps   = res_ps.std_errors
        ci_lo_ps = coefs_ps - 1.96 * ses_ps
        ci_hi_ps = coefs_ps + 1.96 * ses_ps

        yr_coef_ps = {yr: coefs_ps.get(f"treat_{yr}", np.nan) for yr in non_baseline}
        yr_lo_ps   = {yr: ci_lo_ps.get(f"treat_{yr}", np.nan) for yr in non_baseline}
        yr_hi_ps   = {yr: ci_hi_ps.get(f"treat_{yr}", np.nan) for yr in non_baseline}
        yr_coef_ps[BASELINE_YEAR] = 0.0
        yr_lo_ps[BASELINE_YEAR]   = np.nan
        yr_hi_ps[BASELINE_YEAR]   = np.nan

        fig, ax = plt.subplots(figsize=(8, 5))
        ax.axhline(0, color="#888888", linewidth=0.8, linestyle="--", zorder=1)
        ax.axvline(BASELINE_YEAR, color="#bbbbbb", linewidth=0.8, linestyle=":", zorder=1)
        ax.plot(years, [yr_coef_ps[y] for y in years],
                "-", color=BOUNDARY_COLOUR, linewidth=1.0, alpha=0.5, zorder=2)
        nb_c_ps  = [yr_coef_ps[y] for y in non_baseline]
        nb_lo_ps = [yr_coef_ps[y] - yr_lo_ps[y] for y in non_baseline]
        nb_hi_ps = [yr_hi_ps[y] - yr_coef_ps[y] for y in non_baseline]
        ax.errorbar(non_baseline, nb_c_ps, yerr=[nb_lo_ps, nb_hi_ps],
                    fmt="o", color=BOUNDARY_COLOUR, markersize=6,
                    capsize=4, linewidth=1.5, elinewidth=1.5, zorder=3)
        ax.plot(BASELINE_YEAR, 0, "o", color="#333333", markersize=6, zorder=4)
        ax.set_xticks(years)
        ax.set_xlabel("Year")
        ax.set_ylabel("Coefficient (relative to 2020)")
        ax.set_title(
            f"Propensity score  —  DiD event study  (baseline: {BASELINE_YEAR})",
            fontsize=12, pad=10,
        )
        fig.tight_layout()
        fname = out_dir / f"{proj_name}_event_study_pscore.png"
        fig.savefig(fname, bbox_inches="tight")
        plt.close(fig)
        print(f"saved → {fname.name}")
    except Exception as exc:
        print(f"WARN: pscore event study failed ({exc}); skipping.")


# ===========================================================================
# Step 4 — Spatial gradient (64 figures)
# ===========================================================================

def step4_spatial_gradient(panel: pd.DataFrame, figures_dir: Path,
                            proj_name: str) -> None:
    """
    For each of 64 bands, pool all years and estimate:

        Y_it = alpha_i (pixel FE)
               + sum_{d, t != 2020} beta_{d,t} * (Bin_d_i x I[year=t]) + eps_it

    Year 2020 is omitted for identification.  After estimation, each year's
    coefficients are shifted so that the first positive distance bin (0–100 m)
    equals zero, making every line cross y = 0 at that bin.
    Plot one line per year with a colour gradient from YEAR_COLOUR_EARLY to
    YEAR_COLOUR_LATE, connecting the bin coefficients for that year.
    """
    print("\n" + "=" * 65)
    print("Step 4 — Spatial gradient (64 bands)")
    print("=" * 65)

    out_dir = figures_dir / "spatial_gradient"
    out_dir.mkdir(parents=True, exist_ok=True)

    years     = sorted(panel["year"].unique())
    n_years   = len(years)
    dist_bins = sorted(panel["dist_bin"].unique())
    non_baseline = [y for y in years if y != BASELINE_YEAR]

    # The reference bin: first positive distance bin (just outside the boundary).
    # Every year's coefficient line will be shifted so this bin equals zero.
    ref_bin = max(d for d in dist_bins if d >= 0)

    # Two-segment colour ramp:
    #   pre-treatment  (year ≤ 2020): red  → light gray
    #   post-treatment (year ≥ 2020): light gray → blue
    cmap_pre  = mcolors.LinearSegmentedColormap.from_list(
        "pre",  [YEAR_COLOUR_PRE,  YEAR_COLOUR_BASE])
    cmap_post = mcolors.LinearSegmentedColormap.from_list(
        "post", [YEAR_COLOUR_BASE, YEAR_COLOUR_POST])

    pre_years  = [y for y in years if y <= BASELINE_YEAR]
    post_years = [y for y in years if y >= BASELINE_YEAR]

    def _year_colour(yr: int) -> tuple:
        if yr <= BASELINE_YEAR:
            t = (yr - pre_years[0]) / max(pre_years[-1] - pre_years[0], 1)
            return cmap_pre(t)
        else:
            t = (yr - post_years[0]) / max(post_years[-1] - post_years[0], 1)
            return cmap_post(t)

    year_colour = {yr: _year_colour(yr) for yr in years}

    # Set panel MultiIndex
    panel_idx = panel.set_index(["pixel_id", "year"]).sort_index()
    yr_idx  = panel_idx.index.get_level_values("year")
    clusters = panel_idx["dist_bin"]

    # Build interaction dummy matrix once — reused across all 64 bands.
    # For each row, label it with  "bin{d}_yr{t}"  unless year == 2020
    # (the baseline), in which case assign a placeholder that gets dropped.
    print("  Building Bin × Year interaction dummies …", end="  ")
    labels = (
        "bin" + panel_idx["dist_bin"].astype(str)
        + "_yr" + yr_idx.astype(str)
    )
    labels = labels.where(yr_idx != BASELINE_YEAR, other="__ref__")
    X_all  = pd.get_dummies(labels, prefix="", prefix_sep="").astype(float)
    X_all  = X_all.drop(columns="__ref__", errors="ignore")
    print(f"done  ({X_all.shape[1]} interaction columns)")

    band_cols = [f"band_{i:02d}" for i in range(64)]

    for b, band_col in enumerate(band_cols):
        print(f"  Band {b:02d} …", end="  ")

        y = panel_idx[band_col]

        try:
            # Pixel FE only; year variation is captured by the bin × year dummies.
            res = PanelOLS(y, X_all, entity_effects=True).fit(
                cov_type="clustered", clusters=clusters  # type: ignore[arg-type]
            )
        except Exception as exc:
            print(f"WARN: regression failed ({exc}); skipping.")
            continue

        coefs = res.params
        ses   = res.std_errors
        ci_lo = coefs - 1.96 * ses
        ci_hi = coefs + 1.96 * ses

        # --- Collect (bin, year) → (coef, lo, hi) ---
        # Year 2020: all bins are the omitted reference → raw coef = 0
        # Other years: look up estimated coefficient for that bin × year cell
        results = {}
        for d in dist_bins:
            for yr in years:
                if yr == BASELINE_YEAR:
                    results[(d, yr)] = (0.0, 0.0, 0.0)
                else:
                    col = f"bin{d}_yr{yr}"
                    c   = coefs.get(col, np.nan)
                    lo  = ci_lo.get(col, np.nan)
                    hi  = ci_hi.get(col, np.nan)
                    results[(d, yr)] = (c, lo, hi)

        # --- Normalise so ref_bin = 0 for every year ----------------------
        # Subtract the ref_bin coefficient from every bin within each year,
        # so all lines cross y = 0 at the first positive distance bin.
        for yr in years:
            shift = results[(ref_bin, yr)][0]
            for d in dist_bins:
                c, lo, hi = results[(d, yr)]
                results[(d, yr)] = (c - shift, lo - shift, hi - shift)

        # --- Plot ---
        fig, ax = plt.subplots(figsize=(10, 6))

        ax.axhline(0, color="#888888", linewidth=0.8, linestyle="--", zorder=1)
        # Mark the project boundary at distance = 0
        ax.axvline(0, color="#aaaaaa", linewidth=0.8, linestyle=":",
                   label="Project boundary", zorder=1)

        for yr in years:
            colour = year_colour[yr]
            ys_pts = [results[(d, yr)][0] for d in dist_bins]
            lo_pts = [results[(d, yr)][1] for d in dist_bins]
            hi_pts = [results[(d, yr)][2] for d in dist_bins]

            # Shaded 95 % CI ribbon
            ax.fill_between(dist_bins, lo_pts, hi_pts,
                            color=colour, alpha=0.12, zorder=2)
            # Coefficient line
            ax.plot(dist_bins, ys_pts, "-o", color=colour,
                    linewidth=1.8, markersize=4, zorder=3)

        # Legend: show first, middle, and last year to represent the ramp
        legend_years = [years[0], years[n_years // 2], years[-1]]
        handles = [
            Line2D([0], [0], color=year_colour[yr], linewidth=2.5,
                       label=str(yr))
            for yr in legend_years
        ]
        ax.legend(handles=handles, title="Year", loc="upper right",
                  frameon=True, facecolor="white", framealpha=0.85,
                  edgecolor="#999999", fontsize=10, title_fontsize=10)

        ax.set_xlabel("Distance to project boundary (m;  negative = inside)")
        ax.set_ylabel(f"Coefficient (relative to {ref_bin}–{ref_bin + 100} m bin)")
        ax.set_title(
            f"Band {b:02d}  —  Spatial gradient by year",
            fontsize=12, pad=10,
        )

        fig.tight_layout()
        fname = out_dir / f"{proj_name}_spatial_gradient_band{b:02d}.png"
        fig.savefig(fname, bbox_inches="tight")
        plt.close(fig)
        print(f"saved")

    print(f"\n  64 spatial gradient figures → {out_dir}")

    # --- Propensity score spatial gradient (one extra figure) -------------
    print("  Propensity score spatial gradient …", end="  ")
    y_ps = panel_idx["pscore"]
    try:
        res_ps = PanelOLS(y_ps, X_all, entity_effects=True).fit(
            cov_type="clustered", clusters=clusters  # type: ignore[arg-type]
        )
        coefs_ps = res_ps.params
        ses_ps   = res_ps.std_errors
        ci_lo_ps = coefs_ps - 1.96 * ses_ps
        ci_hi_ps = coefs_ps + 1.96 * ses_ps

        results_ps = {}
        for d in dist_bins:
            for yr in years:
                if yr == BASELINE_YEAR:
                    results_ps[(d, yr)] = (0.0, 0.0, 0.0)
                else:
                    col = f"bin{d}_yr{yr}"
                    results_ps[(d, yr)] = (
                        coefs_ps.get(col, np.nan),
                        ci_lo_ps.get(col, np.nan),
                        ci_hi_ps.get(col, np.nan),
                    )

        # Normalise: subtract farthest bin coefficient within each year
        for yr in years:
            shift = results_ps[(ref_bin, yr)][0]
            for d in dist_bins:
                c, lo, hi = results_ps[(d, yr)]
                results_ps[(d, yr)] = (c - shift, lo - shift, hi - shift)

        fig, ax = plt.subplots(figsize=(10, 6))
        ax.axhline(0, color="#888888", linewidth=0.8, linestyle="--", zorder=1)
        ax.axvline(0, color="#aaaaaa", linewidth=0.8, linestyle=":",
                   label="Project boundary", zorder=1)
        for yr in years:
            colour  = year_colour[yr]
            ys_pts  = [results_ps[(d, yr)][0] for d in dist_bins]
            lo_pts  = [results_ps[(d, yr)][1] for d in dist_bins]
            hi_pts  = [results_ps[(d, yr)][2] for d in dist_bins]
            ax.fill_between(dist_bins, lo_pts, hi_pts, color=colour, alpha=0.12, zorder=2)
            ax.plot(dist_bins, ys_pts, "-o", color=colour,
                    linewidth=1.8, markersize=4, zorder=3)

        legend_years = [years[0], years[n_years // 2], years[-1]]
        handles = [Line2D([0], [0], color=year_colour[yr], linewidth=2.5, label=str(yr))
                   for yr in legend_years]
        ax.legend(handles=handles, title="Year", loc="upper right",
                  frameon=True, facecolor="white", framealpha=0.85,
                  edgecolor="#999999", fontsize=10, title_fontsize=10)
        ax.set_xlabel("Distance to project boundary (m;  negative = inside)")
        ax.set_ylabel(f"Coefficient (relative to {ref_bin}–{ref_bin + 100} m bin)")
        ax.set_title("Propensity score  —  Spatial gradient by year", fontsize=12, pad=10)
        fig.tight_layout()
        fname = out_dir / f"{proj_name}_spatial_gradient_pscore.png"
        fig.savefig(fname, bbox_inches="tight")
        plt.close(fig)
        print(f"saved → {fname.name}")
    except Exception as exc:
        print(f"WARN: pscore spatial gradient failed ({exc}); skipping.")


# ===========================================================================
# Entry point
# ===========================================================================

def main() -> None:
    proj        = config.get_project_config()
    figures_dir = config.FIGURES_DIR

    panel = step1_load_panel(proj)
    panel = step2_add_treatment(panel, proj)
    panel = compute_propensity_scores(panel)
    step3_event_study(panel, figures_dir, proj["project_name"])
    step4_spatial_gradient(panel, figures_dir, proj["project_name"])

    print("\n" + "=" * 65)
    print("Done.")
    print("=" * 65)


if __name__ == "__main__":
    main()
    
