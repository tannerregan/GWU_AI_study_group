# Preparing a sample frame guide for Claude

Create a plan to write a python script that will prepare a sample frame for a survey in Kigali. We will write the plan using the Mpazi project as an example, but it should be made easily adaptable to implement the same approach for one or two different projects (we will only find out later which two project areas these are and this code will make sure we are prepared to quickly implement the sample frame construction when we get new project data).

## Script details and python environment

The script(s) should be saved in /code/01_prepare_sample_frame/. Scripts should be well commented and easily understood by a human reader. The kigali_rehousing python environment should be used, and if any new libraries are needed, they should be added and the kigali_rehousing_env.yml should be updated (follow instructions in CLAUDE.md). 

## Input files
The sample frame will use four types of source files (all of these live in C:\Users\tanner_regan\Box\data_main\kigali_rehousing\source/):
1. `plots' /kigali_city_downloads_6may2026/Hosted_Kigali_Parcels_cc_layer0.shp
2. `landuse' /Masterplan2020_Zoning_Phases_22Apr2026_layer0.shp
3. `satembeds' /google_satembed/
    1. Note there are multiple rasterfiles corresponding to different years, and each is broken into multiple tiles
4. `project boundary' /mpazi_project_maps/project_boundary.shp
    1. Note this is a key input that will change when we amend the data to add the two upcoming projects.

## Output and temporary files
All output files should be saved in "C:\Users\tanner_regan\Box\data_main\kigali_rehousing\gen\". They should be well labelled and, if needed, well organized into sub directories. Any files that are generated only to be used internally within the script should be stored in "C:\Users\tanner_regan\Box\data_main\kigali_rehousing\temp\". If the script runs successfully, these temporary files should be automatically deleted at the end of the script. 

## Handling figures
This script will create figures and maps using matplotlib and other libraries. Wherever possible try to follow the style guide and best practices of making figures from Kieran Healy (https://socviz.co/). Be careful - the styleguide is written for R but you are writing a python script! Make sure to translate any R code to Python code and not just copy it directly form the guide. All figures should be saved to "/kigali_rehousing/output/figures/" and they should be given intuitive names.


## Rough workflow in steps

1. Add a 1km buffer to the project boundary
    1. Plot two maps map that include the whole 1km buffer area. The map should include the project boundary in thick blue, and the 1km buffer boundary in thick dashed blue (these should be the top most layer). The first map should use an openstreetmap layer as a background, and the second map should use an google high resolution satellite image as a background. Save the maps to /output/figures/.
2. Create a geodataframe of the subset of plots that intersect the project buffer area. 
    1. Add a column to this gdf that indicates (0,1) whether the plot falls inside the project boundary. For plots that are partially inside and outside the project boundary, assign them =1 if at least 50% of their area is inside the project boundary and =0 otherwise.
    2. Plot the distribution of plot sizes in the project and the distribution outside the project on the same figure. Save the figures to /output/figures/.
    3. Add a column that indicates (0,1) whether the given plot is above the 99th percentile of plot sizes in the project area. NB: only project area plots should be used  to calculate the 99th percentile, but the indicator should be recorded for all plots. 
    4. Plot a map that includes the whole 1km buffer area. The map should include the project boundary in thick blue, and the 1km buffer boundary in thick dashed blue (these should be the top most layer). Add also the subset of plots and use a thin black line for their boundaries. For any plots that are above the 99th percentile size in the project area, their boundary should instead be in gray and their fill should be diagonal hatch lines in red. Save the map to /output/figures/.
3. Create a geodataframe of the subset of landuse polygons that intersect the project buffer area. 
    1. Add a column to this gdf that indicates (0,1) whether the landuse polygon falls inside the project boundary. For polygons that are partially inside and outside the project boundary, assign them =1 if at least 50% of their area is inside the project boundary and =0 otherwise.
    2. Add a column that indicates (0,1) whether the given landuse polygon's "new_zoning" value exists amoung the "new_zoning" values for the polygons that are inside the project boundary. NB: only project area polygons should be used create the set of `feasible' landuse classes, but the indicator should be recorded for all polygons. 
    3. Plot a map that includes the whole 1km buffer area. The map should include the project boundary in thick blue, and the 1km buffer boundary in thick dashed blue (these should be the top most layer). Add also the subset of landuse polygons that have a "new_zoning" that matches the "new_zoning" values in the project area; use a thin black line for their boundaries, and color their fill based on their "new_zoning" column. For any plots that are above the 99th percentile size in the project area, their boundary should instead be in gray and their fill should be diagonal hatch lines in red. Save the map to /output/figures/.
4. Create a layer to be used as data mask 
    1. The layer should start with the 1km project buffer. Then remove any area that intersects plots that are larger than the 99th percentile size cutoff defined above. Then remove any landuse polygons with "new_zoning" values that are not observed inside the project. 
5. Estimate a propensity score raster using google satembeds
    1. Load the satellite embeddings raster from 2020 (the year prior to any construction starting in the Mpazi project). Mask out all raster cells that fall outside of the layer created in step 4 (so that they will be ignored in the following analysis)
    2. Add two layers with the example same spatial dimensions and mask as the satembeds. The first layer is an indicator (0,1) if the pixel falls inside the project boundary. The second layer should be assigned a value that corresponds to the landuse polygon "new_zoning" value that it intersects (note that the "new_zoning" values are strings, so you will need to make a unique mapping between "new_zoning" values and arbitrary integers.)
    3. Now estimate propensity scores for every (unmasked) pixel. Use a probit model with the project indicator as an outcome and on the RHS: indicators for each "new_zoning" value + the value of each 64 satembed layers. 
    4. Plot a map of the propensity scores that includes the whole 1km buffer area. The map should include the project boundary in thick blue, and the 1km buffer boundary in thick dashed blue (these should be the top most layer).  Save the maps to /output/figures/.
    5. Plot the distribution of propensity scores inside the project area and outside the project area on the sample figure.  Save the figure to /output/figures/.
