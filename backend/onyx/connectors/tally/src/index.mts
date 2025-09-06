import process from 'process';
import { tally } from './tally.mjs';
import { database } from './database.mjs';
import { logger } from './logger.mjs'

let isSyncRunning = false;
let lastMasterAlterId = 0;
let lastTransactionAlterId = 0;

function parseCommandlineOptions(): Map<string, string> {
    let retval = new Map<string, string>();
    try {
        let lstArgs = process.argv;

        if (lstArgs.length > 2 && lstArgs.length % 2 == 0)
            for (let i = 2; i < lstArgs.length; i += 2) {
                let argName = lstArgs[i];
                let argValue = lstArgs[i + 1];
                if (/^--\w+-\w+$/g.test(argName))
                    retval.set(argName.substr(2), argValue);
            }
    } catch (err) {
        logger.logError('index.substituteTDLParameters()', err);
    }
    return retval;
}

function invokeImport(): Promise<void> {
    return new Promise<void>(async (resolve) => {
        try {
            isSyncRunning = true;
            await tally.importData();
            logger.logMessage('Import completed successfully [%s]', new Date().toLocaleString());
        }
        catch (err) {
            logger.logMessage('Error in importing data\r\nPlease check error-log.txt file for detailed errors [%s]', new Date().toLocaleString());
        }
        finally {
            isSyncRunning = false;
            resolve();
        }    
    });
}

//Update commandline overrides to configuration options
let cmdConfig = parseCommandlineOptions();
database.updateCommandlineConfig(cmdConfig);
tally.updateCommandlineConfig(cmdConfig);


if(tally.config.frequency <= 0) { // on-demand sync
    await invokeImport();
    logger.closeStreams();
}
else { // continuous sync
    const triggerImport = async () => {
        try {
            // skip if sync is already running (wait for next trigger)
        if(!isSyncRunning) {
            await tally.updateLastAlterId();

            let isDataChanged = !(lastMasterAlterId == tally.lastAlterIdMaster && lastTransactionAlterId == tally.lastAlterIdTransaction);
            if(isDataChanged) { // process only if data is changed
                //update local variable copy of last alter ID
                lastMasterAlterId = tally.lastAlterIdMaster;
                lastTransactionAlterId = tally.lastAlterIdTransaction;
                await invokeImport();
            }
            else {
                logger.logMessage('No change in Tally data found [%s]', new Date().toLocaleString());
            }
        }
        } catch (err) {
            if(typeof err == 'string' && err.endsWith('is closed in Tally')) {
                logger.logMessage(err + ' [%s]', new Date().toLocaleString());
            }
            else {
                throw err;
            }
        }
    }

    if(!tally.config.company) { // do not process continuous sync for blank company
        logger.logMessage('Continuous sync requires Tally company name to be specified in config.json');
    }
    else { // go ahead with continuous sync
        setInterval(async () => await triggerImport(), tally.config.frequency * 60000);
        await triggerImport();
    }
}