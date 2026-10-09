export interface CsvParseResult {
  rows: string[][];
  truncated: boolean;
}

/** Parses RFC 4180 cells, including quoted newlines, with bounded work. */
interface CsvLimits {
  maxRows?: number;
  maxColumns?: number;
  maxCharacters?: number;
  maxCells?: number;
}

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
  let truncated: boolean = content.length > maxCharacters;
  const source = content.slice(0, maxCharacters).replace(/^\uFEFF/, "");
  for (let index = 0; index < source.length; index++) {
    const char = source[index];
    if (char === '"') {
      if (quoted && source[index + 1] === '"') {
        cell += '"';
        index++;
      } else if (quoted || cell === "") quoted = !quoted;
      else cell += char;
    } else if (!quoted && (char === "," || char === "\n" || char === "\r")) {
      if (row.length < maxColumns && cells < maxCells) {
        row.push(cell);
        cells++;
      } else truncated = true;
      cell = "";
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

export function parseCSV(content: string): string[][] {
  return parseCsv(content).rows;
}
