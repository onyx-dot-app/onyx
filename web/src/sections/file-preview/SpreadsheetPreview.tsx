"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { Button, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import { stripBidiControls } from "@opal/utils";
import { parseCsv, SPREADSHEET_PREVIEW_LIMITS } from "@/lib/csv";
import type { SpreadsheetSheet } from "@/lib/types";

const CELL_CLASS =
  "border-b border-e border-border-01 px-3 py-2 align-top whitespace-pre-wrap last:border-e-0 group-last:border-b-0";

interface SpreadsheetPreviewProps {
  // A CSV file is one sheet; the server parses a workbook into its sheets
  sheets: SpreadsheetSheet[];
}

/**
 * Sheets as bordered grids with a sticky header row, and a sheet bar when
 * there are several. Each sheet's CSV parses (RFC 4180) within
 * `SPREADSHEET_PREVIEW_LIMITS`; a cut or malformed sheet says so.
 */
export function SpreadsheetPreview({ sheets }: SpreadsheetPreviewProps) {
  const t = useTranslations("chat.filePreview");
  const [selected, setSelected] = useState(0);
  const sheet = sheets[selected] ?? sheets[0];
  const parsed = useMemo(() => {
    if (!sheet)
      return { rows: [], columns: 0, truncated: false, malformed: false };
    try {
      const { rows, truncated } = parseCsv(
        sheet.csv,
        SPREADSHEET_PREVIEW_LIMITS
      );
      return {
        rows,
        columns: Math.max(0, ...rows.map((row) => row.length)),
        truncated: truncated || sheet.truncated,
        malformed: false,
      };
    } catch {
      return { rows: [], columns: 0, truncated: false, malformed: true };
    }
  }, [sheet]);
  const [header, ...body] = parsed.rows;
  const columns = Array.from({ length: parsed.columns }, (_, index) => index);

  return (
    <Section gap={0} padding={4} alignItems="stretch" justifyContent="start">
      {/* The bottom margin keeps the sheet bar clear of the floating actions */}
      <Section
        gap={0}
        alignItems="stretch"
        justifyContent="start"
        className="mb-12 overflow-hidden rounded-08 border border-border-01 bg-background-neutral-00"
      >
        <div className="min-h-0 flex-1 overflow-auto">
          {(parsed.malformed || parsed.truncated) && (
            <div role="status" className="px-3 py-2">
              <Text as="p" font="secondary-body" color="text-03">
                {parsed.malformed
                  ? t("spreadsheet.malformed")
                  : t("spreadsheet.truncated", {
                      rows: SPREADSHEET_PREVIEW_LIMITS.maxRows,
                      columns: SPREADSHEET_PREVIEW_LIMITS.maxColumns,
                      cells: SPREADSHEET_PREVIEW_LIMITS.maxCells,
                    })}
              </Text>
            </div>
          )}
          {header ? (
            <table className="w-full border-separate border-spacing-0">
              <thead className="sticky top-0 z-10 bg-background-neutral-02">
                <tr>
                  {columns.map((column) => (
                    <th
                      key={column}
                      className="min-w-28 border-b border-e border-border-01 px-3 py-2.5 text-start align-top whitespace-pre-wrap last:border-e-0"
                    >
                      <Text as="p" font="secondary-action" color="text-04">
                        {header[column] ?? ""}
                      </Text>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {body.map((row, rowIndex) => (
                  <tr
                    key={rowIndex}
                    className="group transition-colors hover:bg-background-neutral-02"
                  >
                    {row.map((cell, column) => (
                      <td key={column} className={CELL_CLASS}>
                        <Text as="p" font="secondary-body" color="text-04">
                          {cell}
                        </Text>
                      </td>
                    ))}
                    {/* One empty cell spans the columns that a short row
                        lacks; it holds no data to announce */}
                    {row.length < parsed.columns && (
                      <td
                        aria-hidden
                        colSpan={parsed.columns - row.length}
                        className={CELL_CLASS}
                      />
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            !parsed.malformed && (
              <div className="p-3">
                <Text as="p" font="secondary-body" color="text-03">
                  {t("spreadsheet.empty")}
                </Text>
              </div>
            )
          )}
        </div>
        {sheets.length > 1 && (
          <Section
            height="auto"
            padding={2}
            flexDirection="row"
            justifyContent="start"
            gap={1}
            className="shrink-0 overflow-x-auto border-t border-border-01 bg-background-neutral-02"
          >
            {sheets.map(({ name }, index) => (
              <Button
                key={index}
                size="md"
                prominence={index === selected ? "primary" : "tertiary"}
                aria-pressed={index === selected}
                onClick={() => setSelected(index)}
              >
                {stripBidiControls(name)}
              </Button>
            ))}
          </Section>
        )}
      </Section>
    </Section>
  );
}
