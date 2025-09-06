# Tally to Database: Google BigQuery

## Background
Google BigQuery is a cloud-based Data Warehouse supporting SQL Query syntax for data analytics. It is available for free (Database Size: 10 GB / Query Processing: 1000 GB per month). It requires simple signup to Google Cloud using Gmail account. Google Sheet supports easy integration with Google BigQuery, using which SQL Queries can be fired to to BigQuery and tabular output is return back directly into Google Sheet. Utility supports pushing of Tally data directly into Google BigQuery.

## BigQuery Database Setup
1. Sign-up for a Google BigQuery Free Tier account [Video Tutorial](https://www.youtube.com/watch?v=JLXLCv5nUCE)
1. Create a dataset by name **tallydb** under the default project<br>
![Big Query Create Dataset](https://excelkida.com/image/github/bigquery-create-dataset.png)<br>
![Big Query Create Dataset Options](https://excelkida.com/image/github/bigquery-create-dataset-options.png)
1. Grab databate schema using file under the folder of project [platform/google-bigquery/database-structure.sql](../platform/google-bigquery/database-structure.sql) , dump it to the SQL Query editor window and run it<br>
![Big Query Create Schema SQL](https://excelkida.com/image/github/bigquery-create-schema-sql.png)<br>
![Big Query Dataset Table listing](https://excelkida.com/image/github/bigquery-dataset-table-listing.png)
1. Create service account for connectivity and secured authentication<br>
![Big Query Service Account Menu](https://excelkida.com/image/github/bigquery-create-service-account-menu.png)<br>
![Big Query Service Account Menu](https://excelkida.com/image/github/bigquery-service-account-01.png)<br>
![Big Query Service Account Menu](https://excelkida.com/image/github/bigquery-service-account-02.png)
1. Create and download JSON based key<br>
![Big Query Service Account Menu](https://excelkida.com/image/github/bigquery-service-account-keys-01.png)<br>
![Big Query Service Account Menu](https://excelkida.com/image/github/bigquery-service-account-keys-02.png)<br>
![Big Query Service Account Menu](https://excelkida.com/image/github/bigquery-service-account-keys-03.png)<br>
![Big Query Service Account Menu](https://excelkida.com/image/github/bigquery-service-account-keys-04.png)
1. Copy this JSON based key file into utility folder and rename it to **bigquery-credentials.json**

<br><br>

## Utility configuration
Ensure that in config.json following values are set properly
```json
    "technology": "bigquery"
    "schema": "tallydb"
```
*Note: Do not delete remaining settings (as it may break utility), just keep them unchanged*