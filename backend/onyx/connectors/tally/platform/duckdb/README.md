# Tally to Database: DuckDB

## Background
Setting up RDBMS server is complicated task, especially when light-weight reporting is required. [DuckDB](https://duckdb.org/) offers portable database system (just like SQLite). Individual companies can be stored as single database file which can be easily compressed and emailed. DuckDB also offers simple graphical user interface (browser-based), which can be utilised to analyse data via SQL query. A cloud-based hosting option for DuckDB is offered by platform named [MotherDuck](https://motherduck.com/), which offers free &amp; limited use plan.

## Installation
DuckDB offers portable executable file for Windows (does not require setup or install). Download and extract **duckdb.exe** from zip file, by visiting official download page from the below link
[DuckDB Installation Windows](https://duckdb.org/docs/installation/?version=stable&environment=cli&platform=win&download_method=direct&architecture=x86_64)


## Database Creation &amp; Data Loading
Unlike SQL Server, MySQL, etc., no separate connector for DuckDB is used by the utility. DuckDB supports import of data from CSV files. So, in the *config.json* file, technology needs to be set as **csv**, which would generate CSV files. DuckDB table supports variable length text fields. So the resulting table creation SQL for DuckDB is slightly different compared to other database platform. File data-load.sql is made available, which contains SQL query for table creation and CSV data import. As a pre-requisite, kindly download file **data-load.sql** and place it in the utility directory. By default, **run.bat** file contains command for generating CSV files. Modify the *run.bat* file (using Notepad++) as below:

```bat
node ./dist/index.mjs
.\duckdb tallydb.duckdb -f data-load.sql
```

On executing, it would create a file named **tallydb.duckdb** in the utility folder. Feel free to change filename *tallydb* to match appropriate organisation name. Ensure filename does not have space characters in it. Substitute space character with underscore.

## In-built UI for DuckDB
DuckDB has in-built extension for browsing database file created by it. Simply use the command as below

```bat
.\duckdb -ui tallydb.duckdb
```

Use this UI to draft &amp; test SQL queries. DuckDB offers ODBC driver, which can be installed. Excel supports connectivity to ODBC driver which supports firing SQL queries to DuckDB or using Power Query transformations for further data analysis.