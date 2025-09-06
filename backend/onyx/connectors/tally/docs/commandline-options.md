## Commandline Options
Utility is completely driven by configuration specified in **config.json** file. In case if specific configuration(s) needs to be overriden without changing it in config file, it can be done using commandline switches as follows:

```bat
node ./dist/index.mjs [[--option 01] [value 01] [--option 02] [value 02] ...]
```

**option**: Syntax for option is **--parent-child** , *parent* is the main config name followed by *child* is the sub-config name in **config.json** . (Refer example for further explanation)

**value**: Value of config for corresponsing option

### Examples:

**Scenario 01:** We need to set from & to date dynamically (without changing config file), lets say **FY 2019-20 Q3**, then below is the command for that
```bat
node ./dist/index.mjs --tally-fromdate 20191001 --tally-todate 20191231
```

**Scenario 02:** You have a tally company named *Reliance Industries*, created database of it by name *client_reliance* and want to export **FY 2019-20**  Then below is the command for that
```bat
node ./dist/index.mjs --tally-fromdate 20191001 --tally-todate 20191231 --tally-company "Reliance Industries" --database-schema client_reliance
```

**Scenario 03:** We need to sync data for multiple companies of Tally. So, this requires creation of separate database for each company. And then sync of all the companies in one go can be done like this
```bat
node ./dist/index.mjs --database-schema tallydb_airtel --tally-company "Bharti Airtel"
node ./dist/index.mjs --database-schema tallydb_voda_idea --tally-company "Vodafone Idea Ltd FY 2021-22" --tally-fromdate 20210401 --tally-todate 20220331
node ./dist/index.mjs --database-schema tallydb_jio --tally-company "Reliance Jio from (01-Apr-2022)"
```


**Scenario 04:** Your have a single Tally company with 3 years of data FY 2017-18, FY 2018-19 and FY 2019-20 in it. Full sync for 3 years in single go by setting from-to dates is taking long time with Tally using up large amount of RAM. This can be setup as below with first line of syncing both master and transactions for first year, and then subsequent sync only pushing transactions of that year
```bat
node ./dist/index.mjs --tally-fromdate 20170401 --tally-todate 20180331
node ./dist/index.mjs --tally-fromdate 20180401 --tally-todate 20190331 --tally-master false --tally-truncate false
node ./dist/index.mjs --tally-fromdate 20190401 --tally-todate 20200331 --tally-master false --tally-truncate false
```

The first line instructions sync to run with normal behaviour (with default mode of clear database and sync).
For next 2 years, commandline instructs utility to exclude master from sync (as they were pushed already in previous step), and suppress database clearing, since we are simply pushing (or adding) current year transactions to existing database.