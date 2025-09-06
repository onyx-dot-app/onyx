import http from 'http';
import fs from 'fs';
import child_process from 'child_process';
import { WebSocketServer } from 'ws';
const httpPort = 8997;
const wsPort = 8998;
let isSyncRunning = false;
let syncProcess = undefined;
const wsServer = new WebSocketServer({
    port: wsPort
});
function configObjectToCommandLineArr(obj) {
    let retval = [];
    let databaseObj = obj['database'];
    let tallyObj = obj['tally'];
    for (const [key, val] of Object.entries(databaseObj)) {
        retval.push('--database-' + key);
        retval.push(val);
    }
    for (const [key, val] of Object.entries(tallyObj)) {
        retval.push('--tally-' + key);
        retval.push(val);
    }
    return retval;
}
function runSyncProcess(configObj) {
    let cmdArgs = configObjectToCommandLineArr(configObj);
    syncProcess = child_process.fork('./dist/index.mjs', cmdArgs);
    syncProcess.on('message', (msg) => wsServer.clients.forEach((wsClient) => wsClient.send(msg.toString())));
    syncProcess.on('close', () => {
        isSyncRunning = false;
        wsServer.clients.forEach((wsClient) => wsClient.send('~'));
    });
}
function postTallyXML(tallyServer, tallyPort, payload) {
    return new Promise((resolve, reject) => {
        try {
            let req = http.request({
                hostname: tallyServer,
                port: tallyPort,
                path: '',
                method: 'POST',
                headers: {
                    'Content-Length': Buffer.byteLength(payload, 'utf16le'),
                    'Content-Type': 'text/xml;charset=utf-16'
                }
            }, (res) => {
                let data = '';
                res
                    .setEncoding('utf16le')
                    .on('data', (chunk) => {
                    let result = chunk.toString() || '';
                    data += result;
                })
                    .on('end', () => {
                    resolve(data);
                })
                    .on('error', (httpErr) => {
                    reject(httpErr);
                });
            });
            req.on('error', (reqError) => {
                reject(reqError);
            });
            req.write(payload, 'utf16le');
            req.end();
        }
        catch (err) {
            reject(err);
        }
    });
}
;
const httpServer = http.createServer((req, res) => {
    let reqContent = '';
    req.on('data', (chunk) => reqContent += chunk);
    req.on('end', async () => {
        let contentResp = '';
        if (req.url == '/') {
            let fileContent = fs.readFileSync('./gui.html', 'utf8');
            contentResp = fileContent;
            res.statusCode = 200;
            res.setHeader('Content-Type', 'text/html');
            res.end(contentResp);
            return;
        }
        else if (req.url == '/loadconfig') {
            let fileContent = fs.readFileSync('./config.json', 'utf8');
            contentResp = fileContent;
            res.setHeader('Content-Type', 'application/json');
        }
        else if (req.url == '/saveconfig') {
            fs.writeFileSync('./config.json', reqContent, { encoding: 'utf8' });
            contentResp = 'Config saved';
            res.setHeader('Content-Type', 'text/plain');
        }
        else if (req.url == '/sync') {
            let objConfig = JSON.parse(reqContent);
            if (isSyncRunning) {
                contentResp = 'Sync is already running';
            }
            else {
                isSyncRunning = true;
                runSyncProcess(objConfig);
                contentResp = 'Sync started';
            }
            res.setHeader('Content-Type', 'text/plain');
        }
        else if (req.url == '/abort') {
            if (syncProcess) {
                syncProcess.kill();
                contentResp = 'Process killed';
            }
            else {
                contentResp = 'Could not kill process';
            }
            res.setHeader('Content-Type', 'text/plain');
        }
        else if (req.url == '/list-company') {
            const reqPayload = '<?xml version="1.0" encoding="utf-8"?><ENVELOPE><HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Data</TYPE><ID>MyReportLedgerTable</ID></HEADER><BODY><DESC><STATICVARIABLES><SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT></STATICVARIABLES><TDL><TDLMESSAGE><REPORT NAME="MyReportLedgerTable"><FORMS>MyForm</FORMS></REPORT><FORM NAME="MyForm"><PARTS>MyPart01</PARTS><XMLTAG>DATA</XMLTAG></FORM><PART NAME="MyPart01"><LINES>MyLine01</LINES><REPEAT>MyLine01 : MyCollection</REPEAT><SCROLLED>Vertical</SCROLLED></PART><LINE NAME="MyLine01"><FIELDS>Fld</FIELDS></LINE><FIELD NAME="Fld"><SET>$Name</SET><XMLTAG>ROW</XMLTAG></FIELD><COLLECTION NAME="MyCollection"><TYPE>Company</TYPE><FETCH></FETCH></COLLECTION></TDLMESSAGE></TDL></DESC></BODY></ENVELOPE>';
            let objConfig = JSON.parse(reqContent);
            let result = '';
            try {
                result = await postTallyXML(objConfig['server'], objConfig['port'], reqPayload);
            }
            catch {
                result = '<DATA></DATA>';
            }
            contentResp = result;
            res.setHeader('Content-Type', 'text/xml');
        }
        else if (req.url == '/tally-status') {
            let objConfig = JSON.parse(reqContent);
            try {
                let result = await postTallyXML(objConfig['server'], objConfig['port'], '');
                contentResp = result;
            }
            catch {
                contentResp = '';
            }
            res.setHeader('Content-Type', 'text/plain');
        }
        else {
            res.writeHead(404);
            res.end();
            return;
        }
        res.statusCode = 200;
        res.end(contentResp);
    });
});
httpServer.listen(httpPort, 'localhost', () => {
    console.log(`Server started on http://localhost:${httpPort}`);
    console.log('Launching utility GUI page on default browser...');
    child_process.exec(`start http://localhost:${httpPort}`);
    setInterval(() => {
        if (wsServer.clients.size == 0 && !isSyncRunning) {
            console.log('No webpage connected. Closing utility...');
            process.exit(0); //shutdown utility
        }
    }, 5000);
});
//# sourceMappingURL=server.mjs.map