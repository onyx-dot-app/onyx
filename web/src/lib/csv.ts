import type { SpreadsheetSheet, SpreadsheetPreviewData } from "@/lib/types";

export interface CsvParseResult {
  rows: string[][];
  truncated: boolean;
}

interface CsvLimits {
  maxRows?: number;
  maxColumns?: number;
  maxCharacters?: number;
  maxCells?: number;
}

/** Parses RFC 4180 cells, including quoted newlines, with bounded work. */
export function parseCsv(
  content: string,
  {
    maxRows = Infinity,
    maxColumns = Infinity,
    maxCharacters = Infinity,
    maxCells = Infinity,
  }: CsvLimits = {}
): CsvParseResult {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell: string = "";
  let cells: number = 0;
  let quoted: boolean = false;
  let closedQuote: boolean = false;
  let truncated: boolean = content.length > maxCharacters;
  const source = content.slice(0, maxCharacters).replace(/^\uFEFF/, "");
  for (let index = 0; index < source.length; index++) {
    const char = source[index];
    if (closedQuote && char !== "," && char !== "\n" && char !== "\r")
      throw new Error("Malformed CSV: text after a quoted field");
    if (char === '"') {
      if (quoted && source[index + 1] === '"') {
        cell += '"';
        index++;
      } else if (quoted) {
        quoted = false;
        closedQuote = true;
      } else if (cell === "") quoted = true;
      else throw new Error("Malformed CSV: quote in an unquoted field");
    } else if (!quoted && (char === "," || char === "\n" || char === "\r")) {
      if (row.length < maxColumns && cells < maxCells) {
        row.push(cell);
        cells++;
      } else truncated = true;
      cell = "";
      closedQuote = false;
      if (char !== ",") {
        if (char === "\r" && source[index + 1] === "\n") index++;
        rows.push(row);
        row = [];
        if (rows.length >= maxRows || cells >= maxCells)
          return { rows, truncated: index < source.length - 1 || truncated };
      }
    } else cell += char;
  }
  if (quoted && content.length <= maxCharacters)
    throw new Error("Malformed CSV: unterminated quoted field");
  if (cell || row.length || (source.length > 0 && !/[\r\n]$/.test(source))) {
    if (row.length < maxColumns && cells < maxCells) {
      row.push(cell);
      cells++;
    } else truncated = true;
    rows.push(row);
  }
  return { rows, truncated };
}

export function parseSpreadsheetPreview(
  jsonText: string
): SpreadsheetPreviewData | null {
  try {
    const parsed: unknown = JSON.parse(jsonText);
    if (
      typeof parsed !== "object" ||
      parsed === null ||
      !("sheets" in parsed) ||
      !Array.isArray(parsed.sheets)
    ) {
      return null;
    }
    const sheets: unknown[] = parsed.sheets;
    const validated: SpreadsheetSheet[] = [];
    for (const sheet of sheets) {
      if (
        typeof sheet !== "object" ||
        sheet === null ||
        !("name" in sheet) ||
        typeof sheet.name !== "string" ||
        !("csv" in sheet) ||
        typeof sheet.csv !== "string" ||
        !("truncated" in sheet) ||
        typeof sheet.truncated !== "boolean"
      )
        return null;
      validated.push({
        name: sheet.name,
        csv: sheet.csv,
        truncated: sheet.truncated,
      });
    }
    return { sheets: validated };
  } catch {
    return null;
  }
}

/** Separates malformed CSV from a valid empty spreadsheet. */
export function parseSpreadsheetCsv(content: string) {
  try {
    // Preserve cell whitespace and remove only one final record separator.
    return { rows: parseCsv(content.replace(/\r?\n$/, "")).rows, error: false };
  } catch {
    return { rows: [], error: true };
  }
}
