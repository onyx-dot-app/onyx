# Tally to Database Server: Data Loader Utility
![logo](https://excelkida.com/image/github/tally-database-loader.png)




Commandline utility to load data into Database Server from Tally software, intended for further use by
* MS Excel / Google Sheet (for tabular reports)
* Power BI / Tableau / Google Data Studio (for dashboards)

## Index
* [Version](version)
* [Download](#download)
* [Requirements](#requirements)
* [Graphical User Interface](#graphical-user-interface)
* [Tally XML Server](#tally-xml-server)
* [Database Creation](#database-creation)
* [Utility Installation](#utility-installation)
* [Configuration Setup](#configuration-setup)
    * Database Connection
    * Tally Options
* [Steps](#steps)
* [Tutorial](#tutorial)
* [Understanding Database Structure](docs/data-structure.md)
* [Incremental / Full Sync](docs/incremental-sync.md)
* [Tally Export Config](#tally-export-config)
* [Commandline Options](docs/commandline-options.md)
* [Logs](#logs)
* [Reports](#reports)
* [Google BigQuery](docs/google-bigquery.md)
* [Develop Further](#develop-further)
* [License](#license)
* [Contact](#contact)
* [Credits](#credits)
* [Known Issues](#known-issues)
* [Frequently Asked Questions](docs/faq.md)
* [Release History](docs/release-history.md)

<br><br>

## Version
Latest Version: **1.0.37**<br>
Updated on: **09-Aug-2025**

Note:
1. I keep on fixing utility and adding fields into database. So you are requested to re-create existing databases and re-download utility folder
2. Incremental sync now works for SQL Server / MySQL / PostgreSQL. Going forward two separate version of **database-structure** and **tally-export-config** will be maintained. Files with suffix **incremental** are to be used for **incremental** sync &amp; other are for **full** sync.
3. Structure of config.json file is changed. Ensure to download fresh version of utility


<br><br>

## Download

Database Loader Utility is portable, and does not have a setup wizard like we find for software installation. Zip archive of utility can be downloaded from below link. Kindly use open-source &amp; free software [7-zip file archiver](https://www.7-zip.org/download.html) to un-compress utility archive.

[Download Database Loader Utility](https://excelkida.com/resource/tally-database-loader-utility-1.0.37.7z)

Also, it is a command-line utility having no window interface (to keep it minimal and faster)

<br><br>

## Requirements
Utility requires installation of following as a pre-requisite (along with download link)
* Windows 10
* [Tally Prime](https://tallysolutions.com/download/)
* [Node JS](https://nodejs.org/en/)
* Database Server (supports any of below)
    * [Microsoft SQL Server](https://www.microsoft.com/en-ie/sql-server/sql-server-downloads/)
    * [PostgreSQL](https://www.postgresql.org/download/)
    * [MySQL](https://dev.mysql.com/downloads/mysql/)
    * [MariaDB](https://mariadb.org/download/)
    * [Google BigQuery](https://cloud.google.com/bigquery/)

Free version of all the above Database Servers are available for download. Also all of them are available on popular cloud like Microsoft Azure / Google Cloud Platform / Amazon Web Services

Preferred versions:
* SQL Server - version 2019
* MySQL - version 8.x
* PostgreSQL - 11.x or above

**Note:** *Utility and SQL Queries for reports are deviced considering latest version of the above Database Server. Running it in lower version might hamper few of the functionalities, as some SQL syntax were introduced in latest version*

<br><br>

## Graphical User Interface
Utility is available in 2 types of interfaces
1. Command-line based which can be invoked using **run.bat** file
1. Browser-based interface which can be invoked using **run-gui.bat** file

Both use the same back-end. File **run-gui.bat** uses browser-based interface which offers following features:
* Ease of editing config.json values (without requiring Notepad)
* Automatic default value setting based on dropdown to minimize invalid configuration values
* Option to send configuration to utility without requiring it to save (suggested when user do no wish to save &amp; reveal password in config.json file)

**Note:** *Please do not close the command-line window which acts as temporary webserver to interact with browser. Close it only after you close the browser tab of the utility.*

<br><br>

## Tally XML Server
Tally has in-built XML Server capability, which can import/export data in/out of Tally. This utility sends export command to Tally along with report specification written in TDL (Tally Developer Language) in XML format. In response, Tally returns back the requested data (in XML format), which is then imported into Database Server. 

* Help (F1) > Settings > Connectivity
* Client/Server configuration
* Set TallyPrime is acting as **Both**

<br>

**Note: Support for Tally.ERP 9 has been removed, to keep database aligned to Tally Prime. Kindly upgrade to Tally Prime.**

<br><br>



## Database Creation
Database first needs to be created and then Tables needs to be created in which data from Tally will be loaded, before running utility. File **database-structure.sql** contains SQL for creating tables of database. Just ensure to create database using any of GUI Database Manager. That database name should be updated in **schema** property of *config.json*. Open-source database editor available freely are
* [SQL Server Management Studio (SQL Server)](https://docs.microsoft.com/en-us/sql/ssms/download-sql-server-management-studio-ssms)
* [pgAdmin (PostgreSQL Server)](https://www.pgadmin.org/download/)
* [MySQL Workbench (MySQL Server)](https://dev.mysql.com/downloads/workbench/)
* [Heidi SQL (SQL Server / MySQL / MariaDB / PostgreSQL)](https://www.heidisql.com/download.php/)

Note: Database structure creation SQL script for PostgreSQL is avilable inside **platform/postgresql** folder of project. In future, database technology-wise separate SQL Script will be available for individual technologies.

Utility support import into database server installed and hosted on
* Same PC where Tally is
* On any machine on LAN
* Virtual Private Server
* Cloud Database [ Microsoft Azure / Amazon Web Services (AWS) / Google Cloud Platform / Oracle Cloud ]

<br><br>

## Configuration Setup
Utility contains a file **config.json** containing database connection and tally related settings.

<br>

### Database Connection
Database Connection credentials needs to be set in the file in **database** section of *config.json*. A sample configuration file

**SQL Server**
```json
"database": {
    "technology": "mssql",
    "server": "localhost",
    "port": 1433,
    "ssl": false,
    "schema": "<database_name>",
    "username": "sa",
    "password": "<your_password>",
    "loadmethod": "insert"
}
```
<br/>

**MySQL / MariaDB Server**
```json
"database": {
    "technology": "mysql",
    "server": "localhost",
    "port": 3306,
    "ssl": false,
    "schema": "<database_name>",
    "username": "root",
    "password": "<your_password>",
    "loadmethod": "insert"
}
```

**PostgreSQL Server**
```json
"database": {
    "technology": "postgres",
    "server": "localhost",
    "port": 5432,
    "ssl": false,
    "schema": "<database_name>",
    "username": "postgres",
    "password": "<your_password>",
    "loadmethod": "insert"
}
```

<br/>

| Settings | Value |
| --- | --- |
| technology | **mssql**: Microsoft SQL Server<br>**mysql**: MySQL Server or MariaDB Server<br>**postgres**: PostgreSQL Server<br>**bigquery**: Google BigQuery<br>**adls**:Azure Data Lake storage<br>**json**: JSON file<br>**csv**: Generate CSV dump for further import (below parameters of database connection are dummy when CSV setting is applied) |
| server | IP Address of PC on which Database Server is hosted (**localhost** = same machine) |
| port | Port number on which Database Server is listening<br>**mssql**: Default port is **1433**<br>**mysql**: Default port is **3306**<br>**postgres**: Default port is **5432** |
| ssl | **true**: Secured (to be used only if Database Server is on Cloud)<br>**false**: Unsecured [*default*] (to be used when Database Server is on same machine / within LAN / within VPN)<br>Supported for mssql / postgres only |
| schema | Database name in which to insert data |
| username | Username<br>**mssql**: Default user is **sa** <br>**mysql**: Default user is **root**<br>**postgres**: Default user is **postgres** |
| password | Password for corresponding user. It is set during installation of Database Server.<br>*Note: Trusted Login (password-less) of SQL Server not supported by this utility* |
| loadmethod | **insert**: loads rows in database tables using SQL query with multiple rows. This is most compatible method which works everywhere (Compatibility: **High** / Performance: **Slow** ) <br> **file**: loads rows in database table using file based loading method. This method works only when database server and utility is running on same machine. So this method is not compatible with Cloud databases (Compatibility: **Low** / Performance: **Fast** ) |

Kindly override configurations, as per respective Database Server setup

**Note**: *Utility supports SQL Server connection via TCP/IP port only. This option is disabled by default, which needs to be enabled. Kindly refer FAQ where it has been elaborated in detail along with screenshots*
 (applicable for Microsoft SQL Server only)

<br>

### Tally Options
Few of the options of Tally may need modification, if default settings of Tally are specifically over-ridden (due to port clashes). A sample configuration of tally is demonstrated as below

## Full sync

```json
"tally": {
     "definition": "tally-export-config.yaml",
     "server": "localhost",
     "port": 9000,
     "fromdate" : "20230401",
     "todate" : "20240331",
     "sync": "full",
     "frequency": 0,
     "company": ""
}
```

## Incremental sync

```json
"tally": {
     "definition": "tally-export-config-incremental.yaml",
     "server": "localhost",
     "port": 9000,
     "fromdate" : "auto",
     "todate" : "auto",
     "sync": "incremental",
     "frequency": 5,
     "company": ""
}
```

| Setting | Value |
| --- | --- |
| definition | Name of export config file in the utility folder. This setting is to be used for easy switching between incremental and full sync, as both the files contains different structure  |
| server | IP Address or Computer Name on which Tally XML Server is running (**localhost** is default value equivalent of IP Address 127.0.0.1). Change this if you need to capture data from a Tally running on different PC on your LAN |
| port | By default Tally runs XML Server on port number **9000**. Modify this if you have assigned different port number in Tally XML Server settings (typically done when you want run Tally.ERP 9 and Tally Prime both at a same time parallely, where you will be changing this port number) |
| master / transaction | **true** = Export master/transaction data from Tally (*default*) <br> **false** = Skip master/transaction data |
| fromdate / todate | **YYYYMMDD** = Period from/to for export of transaction and opening balance (in 8 digit format) <br> **auto** = This will export complete transactions (irrespective of selected Financial Year) from Tally by auto-detection of First & Last date of transaction |
| sync | **full** = Sync complete data from Tally to Database Server (*default*)<br> **incremental** = Sync only that data which was added/modified/delete from last sync |
| frequency | ping frequency in minutes to Tally to monitor changes in data and trigger sync (0 = off i.e. just run sync once and close it) |
| company | Name of the company from which to export data or leave it blank to export from Active company of Tally (this parameter is intended for use when user needs to export data from specific company irrespective of it is active or not. Setup a powershell script to run a loop when multiple companies needs to be targeted one-by-one) |

<br><br>

## Steps
1. Create database in Database Server along with tables inside it (use **database-structure.sql** to create tables)  [ignore if already created]
1. Ensure options are properly set in **config.json**
1. Ensure Tally is running and target company from which to export data is Active
1. Run the file **run.bat**
1. Commandline window will open, attempt to import data and will get closed after import/error
1. Check for import status in **import-log.txt** file and errors (if any) in **error-log.txt** file

<br><br>

## Tutorial

YouTube tutorial video are availabe (link below)

**SQL Server**
<br>

[![YouTube tutorial SQL Server](https://img.youtube.com/vi/Am0uspXtTzM/0.jpg)](https://www.youtube.com/watch?v=Am0uspXtTzM)

<br>

**MySQL Server**
<br>

[![YouTube tutorial MySQL Server](https://img.youtube.com/vi/_bXc54bKTlI/0.jpg)](https://www.youtube.com/watch?v=_bXc54bKTlI)

<br><br>

## Tally Export Config
Certain times we may require to add or remove any of the fields from export (to add user defined fields created by TDL Developer in Tally customisations). So this export specification is defined in **tally-export-config.yaml** file in YAML format. This file is divided into Master and Transaction, containing multiple tables in it. To understand structure and nomenclature, an example of this is given below

```yaml
master:
    - name: mst_group
      collection: Group
      fields:
        - name: guid
          field: Guid
          type: text
```

name: mst_group (**Database Table name**)<br>
collection: Group (**Tally Collection name**)<br>
name: guid (**Database Column name**)<br>
field: Guid (**Tally field name**)<br>
type: **text / logical / date / number / amount / quantity / rate / custom**

**amount:** Credit = positive / Debit = negative<br>
**quantity:** In Quantity = positive / Out Quantity = negative<br>
**rate:** Rate type of data (is always positive)<br>
**custom:** Any custom expression in TDL format


<br><br>

## Logs
Utility creates log of import specifying how many rows in each tables were loaded. This log can be found in **import-log.txt** file. If any error occurs, then details of error(s) are logged in **error-log.txt** file

<br><br>

## Reports
Project hosts library of SQL Queries to generate some popularly used reports, required for preparing Dashboards in Microsoft Power BI and Google Data Studio. Due to minor difference in SQL syntax & functions of SQL Server and MySQL, SQL for same report is provided for both of these Server platforms.

Author actively supports **Google BigQuery** (fully cloud-based solution of Google), and even shared equivalent SQL query for BiQuery. BigQuery acts as a input for Google Data Studio Dashboards and also supports easy export of tabular output to Google Sheets. Interested users can sign-up for a free [Google Cloud account](https://cloud.google.com) and use BigQuery with free daily limits

<br><br>


## Develop Further
If you intend to develop and modify this utility further to next level for your use-case, then you can clone this project from Git and run the project as below
1. Clone the project repository
1. Install Visual Studio and open the project repository folder
1. Install required npm packages by following command **npm install**
1. Install global instance of typescript compiler available on Node Package Manager by following command **npm install typescript -g**
1. Run the project in Visual Studio code (**launch.json** file already provided in **.vscode** folder to run it with required settings)

<br><br>

## License
This project is under MIT license. You are free to use this utility for commercial & educational purpose.

<br><br>

## Contact
Project developed & maintained by: **Dhananjay Gokhale**

For any query email to **info@excelkida.com** or Whatsapp on **(+91) 90284-63366**

<br><br>

## Credits
Bug fixes or enhancements from various contributors

* [CA Venugopal Gella](https://github.com/gellavenugopal) - Fixing of Tally Prime 2.0.1 export issue

## Known Issues
* When multiple companies are selected in Tally &amp; specific company name is specified in config.json, it has been observed that in a rare case (especially on Windows Server), Tally fails to fetch data from that target company &amp; internally produces an error that specified company is not loaded.
* It has been observed that sometimes when Tally remain running for several days on PC then in a rare case Tally fails to return back updated / latest data (especially on Windows Server) &amp; you may have to restart Tally.
* If you have configured automatic sync of data via Windows Task Schedular, then make sure you don't log-off, but just disconnect as Tally is graphical based software.
