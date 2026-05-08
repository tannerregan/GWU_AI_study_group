Create a plan that makes the following adjustments to this code.

1. The map legends on all maps need to be bigger and have their own background so that they can be read clearly.
2. Reset the plot size threshold to the 99.9th percentile and add a lower bound cutoff at the 0.1th percentile.
3. The hatch design on all maps should be changed: the background should be fully transparent, but the diagonal lines should be solid red. 
4. Make some substantial changes to the landuse approach: 
    1. For the map, simply display all landuse polygons (do not cross out ones that don't appear in the project area). Make sure each unique value of "new_zoning" gets a unique color. 
    2. For the mask, rather than selecting "new_zoning" values that are observed in the project area, select only polygons with "zone_code"='R2' (other zone codes should be masked out.)
5. When selecting plots inside the buffer, do not clip them with the buffer. Instead they should be selected and retained if they intersect the buffer area (the plot shapes should not be changed).
6. Check whether it is possible to use google high resolution satellite imagery from 2020 as the back ground of the map. If yes, replace the map with satellite imagery with one that is specifcally from 2020. Then add a second map in the same style that uses a very high resolution satellite image that is more recent (e.g. since 2025). 
7. For the propensity score, remove the land use categories - so only the satembeds are used as predictors.

8. Finally step 5 did not run, and gave the error: "UnboundLocalError: cannot access local variable 'rasterio' where it is not associated with a value"