# Sync Options

## Background
Time to sync is dependent on the volumn of data in the Tally. In few scenario where data is huge, sync time can be very long.
Utility supports 2 types of sync

**full**: Complete data is sync to database freshly

**incremental**: Only that portion of data is sync which got added / modified / deleted from the last sync point

## Steps for incremental sync
1. Delete and re-create database using file **database-structure-incremental.sql**
1. In the **config.json** file, set **sync** setting value to **incremental** , **frequency** to any value greater than zero (i.e. no of minutes utility need to reach out Tally again to check for changes in data) and **definition** to **tally-export-config-incremental.yaml** . From/To date is ignored and set to auto internally.
1. Carefully set name of the target company of Tally in *company* setting, as it is not advisable to keep company name blank which picks data from active company which could cause mess if it points to incorrect database
1. Run the **run.bat** file

## Compatibility
Incremental sync option is compatible only for RDBMS types of database i.e.
1. SQL Server
1. MySQL Server
1. PostgreSQL Server

Incremental sync for Google BigQuery is currently not introduced, as UPDATE query of SQL in Google BigQuery incurs high cost beyond free usage limit.

## Incremental Sync - Known Limitations
* Date From/To parameter of config.json is disabled during incremental sync (it is set to *auto* as a default), as utility cannot track if changes to data outside period were made or not. It is recommended to run incremental sync on single Financial Year data.
* During prelimnary Full sync required for subsequent incremental sync, period should be kept as *auto* & frequency as zero
* Existing data should not be deleted from database manually using DELETE / TRUNCATE SQL command when using incremental sync, as it may break sync and cause data ingegrity issues
* Setting incorrect database name in subsequency incremental sync will cause data integrity issues.
* **incremental** sync option needs to be used judiciously when it is bare necessity. Prefer **full** sync which is safe compared to incremental sync.
