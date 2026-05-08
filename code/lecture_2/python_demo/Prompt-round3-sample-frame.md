Now we will add one final step that builds the actual sampling frame. Create a plan that adds in the following:

1. create a hexagonal grid that covers the buffer area
2. Remove any hexagon with a centroid that falls into a plot larger than the upper limit cutoff applied to plot sizes.
3. Create a layer that takes the subset of landuse polygons with zone_code=R2 or R1. Then buffer this layer out by 20m and then buffer back in by 20m (this will fill up 'holes' created by roads that run between these landuse polygons).
4. Remove any hexagon with a centroid that falls outside of this new landuse layer. This is our sample frame. Add a column that indicates if the hexagon's centroid falls into the project boundary. Add a column that measures the distance from the hexagon centroid to the project boundary - hexagons inside the project boundary should take negative values.
5. Make a map of the buffer area (like the others) with the selected hexagons. The hexagons should be transparent with thin black boundaries.
6. Make a histogram of the project boundary distances: the x-axis should be the distance to the project boundary (binned into 100m bins) and the y-axis should be count of plots in the distance bin.
