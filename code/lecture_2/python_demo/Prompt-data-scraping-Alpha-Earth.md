# Alpha Earth data scraping guide for Claude

Create a plan to write a python script that will download data from Google Earth Engine. The script should collect data from GOOGLE_SATELLITE_EMBEDDING_V1_ANNUAL. The earth engine catalogue describes the dataset: https://developers.google.com/earth-engine/datasets/catalog/GOOGLE_SATELLITE_EMBEDDING_V1_ANNUAL?utm_source=deepmind.google&utm_medium=referral&utm_campaign=gdm&utm_content=#description

The script(s) should be saved in /code/02_google_satembed_download/. The kigali_rehousing python environment should be used, and if any new libraries are needed, they should be added and the kigali_rehousing_env.yml should be updated (follow instructions in CLAUDE.md). A key new library will be earthengine-api. 

I would like the raster data output to be saved locally, however it is my understanding that the earthengine-api can only output data to a google drive. Please confirm whether that is the case and if it is proceed with my instructions. If it is not the case then please write the script to save directly to C:/Users/tanner_regan/downloads/kigali_downloads/. 

I want to the script to follow broad steps:
1. Confirm that the raster dataset that we intend to download is not "too big". Do not try to download something that is more than 2GB. 
    1. First try to download a raster with an extent that covers the project area plus a 3km buffer. The project boundaries can be found here: C:\Users\tanner_regan\Box\data_main\kigali_rehousing\source\mpazi_project_maps/project_boundary.shp
    2. If the resulting raster is too large, then try a smaller buffer: 2km and then 1km.
2. Once you have identified an extent we want to extract the satellite embedding data as a raster clipped to this extent 
    1. The feature collection is available at ee.ImageCollection("GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL")
    2. Download a raster for the year 2020, but make the script easy to adjust because we will want to update it later to download multiple years.
    3. For every raster that gets downloaded 
        1. give it an intuitive filename that specifies the feature collection it came from and the dates/year that it comes from.
        2. Write a short note in a [filename]_readme.txt with the same [filename] as the downloaded file. The readme should give a very short note on where the data came from (also provide an exact link) and a date that the data was dowloaded. Include other relevant details like data version number, and any other information that is helpful to understand the data.
    4. Even though we select the extent so that the file is not too large, it may still be too large to download in one shot. If so, the script should work in batches.
    5. The raster should be saved as a georeferenced .tiff file
    6. Print descriptive messages on the download progress.  
3. It is very important that the whole workflow will work so yuou mus do sufgficient checks before hand in order to ensure that the whole script will run all the way through. A key bottle neck will be the decision to save rasters to google drive, or if you can manage to directly save it locally. I do have a preference for it to be saved locally but do not try to do this if you anticipate it to be error prone or add time consuming steps. 
    1. You will likely need to use google drive even if its just an intermediate step. Mount the google drive with the path "/content/drive/"
    2. Any data that needs to be saved in google drive, even temporarily, should be saved in  "/content/drive/MyDrive/GEE_temp/"







