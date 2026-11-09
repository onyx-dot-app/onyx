import { read, utils } from "xlsx";
import { SPREADSHEET_PREVIEW_LIMITS } from "@/lib/csv";

export interface ParsedSpreadsheetSheet {
  name: string;
  rows: string[][];
  truncated: boolean;
}

/** Show saved cell values without executing formulas or rendering workbook HTML. */
export function parseSpreadsheet(
  buffer: ArrayBuffer
): ParsedSpreadsheetSheet[] {
  const { maxRows, maxColumns, maxCells, maxCharacters } =
    SPREADSHEET_PREVIEW_LIMITS;
  const workbook = read(buffer, {
    type: "array",
    sheetRows: maxRows + 1,
    cellHTML: false,
    cellFormula: false,
  });
  return workbook.SheetNames.filter(
    (name, index) => !workbook.Workbook?.Sheets?.[index]?.Hidden
  ).map((name) => {
    const sheet = workbook.Sheets[name];
    if (!sheet?.["!ref"]) return { name, rows: [], truncated: false };
    const range = utils.decode_range(sheet["!ref"]);
    const original = utils.decode_range(sheet["!fullref"] || sheet["!ref"]);
    const lastColumn = Math.min(range.e.c, range.s.c + maxColumns - 1);
    const columns = lastColumn - range.s.c + 1;
    const lastRow = Math.min(
      range.e.r,
      range.s.r + Math.min(maxRows, Math.floor(maxCells / columns)) - 1
    );
    let truncated = original.e.c > lastColumn || original.e.r > lastRow;
    const rows = utils.sheet_to_json<string[]>(sheet, {
      header: 1,
      raw: false,
      defval: "",
      blankrows: true,
      range: { s: range.s, e: { r: lastRow, c: lastColumn } },
    });
    let remaining = maxCharacters;
    return {
      name,
      rows: rows.map((row) =>
        row.map((cell) => {
          const text = String(cell);
          const value = text.slice(0, Math.max(0, remaining));
          remaining -= value.length;
          if (value.length < text.length) truncated = true;
          return value;
        })
      ),
      truncated,
    };
  });
}
