// CsvContent
import React from "react";

export function parseCSV(text: string): string[][] {
  const rows: string[][] = [];
  let field = "";
  let fields: string[] = [];
  let inQuotes = false;

  for (let i = 0; i < text.length; i++) {
    const char = text[i];

    if (inQuotes) {
      if (char === '"') {
        if (i + 1 < text.length && text[i + 1] === '"') {
          field += '"';
          i++;
        } else {
          inQuotes = false;
        }
      } else {
        field += char;
      }
    } else if (char === '"') {
      inQuotes = true;
    } else if (char === ",") {
      fields.push(field);
      field = "";
    } else if (char === "\n" || char === "\r") {
      if (char === "\r" && i + 1 < text.length && text[i + 1] === "\n") {
        i++;
      }
      fields.push(field);
      field = "";
      rows.push(fields);
      fields = [];
    } else {
      field += char;
    }
  }

  if (inQuotes) {
    throw new Error("Malformed CSV: unterminated quoted field");
  }

  if (field.length > 0 || fields.length > 0) {
    fields.push(field);
    rows.push(fields);
  }

  return rows;
}
