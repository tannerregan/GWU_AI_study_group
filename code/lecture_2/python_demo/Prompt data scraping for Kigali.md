# Kigali City data scraping guide for Claude

Create a plan for to write a python script or two that will scrape the Kigali City Master Plan website for their publicly available data. The script(s) should be saved in /code/02_gis_download/. The kigali_rehousing python environment should be used, and if any new libraries are needed, they should be added and the kigali_rehousing_env.yml should be updated. There are two urls with content that I would like to download 
1. https://masterplan.kigalicity.gov.rw/server/rest/services/Hosted
2. https://masterplan.kigalicity.gov.rw/server/rest/services/Masterplan2020

I want to the script to do two broad steps:
1. Print out all of the folders and sub-folders at each of the two links above. Only report those that are "FeatureServers", ie. do not report the "MapServer" folders and subfolders since these are not useful for downloading data (correct me if you think I am mistaken on this). Include this printed folder structure in the plan that you create, if possible.
2. Download each FeatureServer that you find at the two links above. When doing so the script should be designed considering the following:
    1. Print descriptive messages on which files have been downloaded, and the progress of each.  
    2. Design the script carefully so that the server doesn't cut us off from too many queries, or give us any other errors. It is important for you to check first whether the script will return a download error before downloading the entire file. We want to avoid any download errors as much as possible.
    3. The files may be large, so the script should work in batches if needed.
    4. Files should be saved in C:/Users/tanner_regan/downloads/kigali_downloads/ and each file should be given a unique name that corresponds to the path name used to identify it on the server.
    5. When a file has been downloaded successfully, add a short note in a [filename]_readme.txt with the same [filename] as the downloaded file. The readme should give a very short note on where the data came from (provide an exact link if possible) and a date that the data was dowloaded. 
    6. optional - the files are available as json and geojson, but in the end we will want to save them as shapefiles. If it makes it easier or more efficient, you can do this conversion as part of the scraping script. If it makes it more difficult or less efficient then the files can be saved as json. 






