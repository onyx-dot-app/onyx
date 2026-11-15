import type { ParsedSpreadsheetSheet } from "@/lib/spreadsheetPreview";

export type SpreadsheetWorkerResult =
  | { sheets: ParsedSpreadsheetSheet[] }
  | { error: string };

/** Keep workbook decompression and parsing off the UI thread, with a bounded lifetime. */
export function readSpreadsheetPreview(
  buffer: ArrayBuffer
): Promise<ParsedSpreadsheetSheet[]> {
  return new Promise((resolve, reject) => {
    const worker = new Worker(
      new URL("./spreadsheetPreview.worker.ts", import.meta.url),
      { type: "module" }
    );
    const timeout = setTimeout(() => {
      worker.terminate();
      reject(new Error("Spreadsheet preview timed out"));
    }, 10_000);
    worker.onmessage = (event: MessageEvent<SpreadsheetWorkerResult>) => {
      clearTimeout(timeout);
      worker.terminate();
      if ("error" in event.data) reject(new Error(event.data.error));
      else resolve(event.data.sheets);
    };
    worker.onerror = () => {
      clearTimeout(timeout);
      worker.terminate();
      reject(new Error("Unable to parse spreadsheet"));
    };
    worker.postMessage(buffer, [buffer]);
  });
}
