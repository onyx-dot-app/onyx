import { parseSpreadsheet } from "@/lib/spreadsheetPreview";
import type { SpreadsheetWorkerResult } from "@/lib/readSpreadsheetPreview";

self.onmessage = (event: MessageEvent<ArrayBuffer>) => {
  try {
    self.postMessage({
      sheets: parseSpreadsheet(event.data),
    } satisfies SpreadsheetWorkerResult);
  } catch {
    self.postMessage({
      error: "Unable to parse spreadsheet",
    } satisfies SpreadsheetWorkerResult);
  }
};
