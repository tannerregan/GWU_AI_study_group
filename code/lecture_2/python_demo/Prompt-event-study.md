# Running event studies guide for Claude

Create a plan to write a python script that will create event study graphs using the satembeds as outcomes, and the sample frame as a sample. Use the paper by Douglas L. Miller as a guide for event study models: https://pubs.aeaweb.org/doi/pdfplus/10.1257/jep.37.2.203

## Script details and python environment

The script(s) should be saved in /code/01_prepare_sample_frame/. Scripts should be well commented and easily understood by a human reader. The kigali_rehousing python environment should be used, and if any new libraries are needed, they should be added and the kigali_rehousing_env.yml should be updated (follow instructions in CLAUDE.md). 

## Input files
The sample frame will use two types of input files (all of these live in C:\Users\tanner_regan\Box\data_main\kigali_rehousing\):
1. `satembeds' /source/google_satembed/
2. `sample frame' /gen/mpazi/sample_frame.gpkg
3. `project boundary' /source/mpazi_project_maps/project_boundary.shp

## Output and temporary data files
There should be no output data files nor temporary data files

## Handling figures
This script will create figures and maps using matplotlib and other libraries. Wherever possible try to follow the style guide and best practices of making figures from Kieran Healy (https://socviz.co/). Be careful - the styleguide is written for R but you are writing a python script! Make sure to translate any R code to Python code and not just copy it directly form the guide. All figures should be saved to "/kigali_rehousing/output/figures/" and they should be given intuitive names.


## Rough workflow in steps

1. Load the satembeds for each available year.
2. in the satembeds, mask out all pixels that fall outside of the sample frame hexagons
3. use the project boundary to add two raster layers that match the spatial dimensions of the masked satembeds. The first layer should be an indicator if the pixel falls inside the project boundary. The second layer should take the value of the distance from the pixel centroid to the project boundary - pixels inside the project boundary should take negative values.
4. Now using the stack of rasters, run an event study for each satembed vector (so 64 figures in total). Where y=satembed and treatment=inside project area. 2020 should be the baseline year. Since there are many figures, put them all in a subfolder in /figures/.
5. Create a second set of figures, again one for each satembed vector (so 64 figures in total). Where y=satembed is regressed on distance to project boundary (binned into 100m bins) interacted by satembed-year. Then plot the coefficients connecting those from the same years as a line and giving them the same color. The colors should start at one solid color for the earliest year, and then smoothly transition to a solid color for the final year. 