# Plan: Add Propensity-Score Outcome to Event Study & Spatial Gradient

## Context
The event study currently runs 64 regressions — one per satembed band. The user wants one
additional figure for each analysis (event study + spatial gradient) where the outcome is the
pixel-level propensity score predicted by a probit model fitted on 2020 satembed data. The probit
model is the same as in `prepare_sample_frame.py` Step 5: `Probit(in_project ~ band_00…band_63)`,
estimated on 2020 pixels only, then applied to every year to produce a time-varying scalar outcome.

---

## File to modify
`code/01_prepare_sample_frame/event_study.py`

---

## Changes

### 1. Add `statsmodels` import
```python
import statsmodels.api as sm
```

### 2. New helper function — insert between step2 and step3
```python
def compute_propensity_scores(panel: pd.DataFrame) -> pd.DataFrame:
    """
    Fit a probit model on 2020 pixels (outcome = in_project, features = 64 bands)
    and apply it to every year to produce a 'pscore' column.
    Uses the same specification as prepare_sample_frame.py Step 5.
    """
    band_cols = [f"band_{i:02d}" for i in range(64)]
    data_2020 = panel[panel["year"] == BASELINE_YEAR]

    X_2020 = sm.add_constant(data_2020[band_cols].astype(float))
    y_2020 = data_2020["in_project"].astype(float)

    print("  Fitting 2020 probit model for propensity scores …")
    probit_res = sm.Probit(y_2020, X_2020).fit(maxiter=100, disp=False)

    # Apply to all years
    X_all = sm.add_constant(panel[band_cols].astype(float))
    panel = panel.copy()
    panel["pscore"] = probit_res.predict(X_all)
    print(f"  Propensity score range: {panel['pscore'].min():.3f} – {panel['pscore'].max():.3f}")
    return panel
```

### 3. Call it in `main()` between step2 and step3
```python
panel = compute_propensity_scores(panel)
```

### 4. Event study — add one pscore figure after the 64-band loop
Reuse the existing `panel_idx`, `yr_idx`, `clusters`, and the same plot logic from step3.
Y variable: `panel_idx["pscore"]`.
X: same treat_yr dummies.
Output: `out_dir / f"{proj_name}_event_study_pscore.png"`.

### 5. Spatial gradient — add one pscore figure after the 64-band loop
Reuse `X_all` dummies, `clusters`. Y variable: `panel_idx["pscore"]`.
Same plot logic as step4, same normalization (subtract farthest bin per year).
Output: `spatial_gradient out_dir / f"{proj_name}_spatial_gradient_pscore.png"`.

---

## Output files produced
- `output/figures/event_study/mpazi_event_study_pscore.png`
- `output/figures/spatial_gradient/mpazi_spatial_gradient_pscore.png`

---

## Verification
Run: `conda activate kigali_rehousing && python code/01_prepare_sample_frame/event_study.py`
Check two new PNG files appear in the event_study/ and spatial_gradient/ subfolders.
