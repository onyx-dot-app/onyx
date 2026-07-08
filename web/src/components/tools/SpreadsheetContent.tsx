// SpreadsheetContent — renders xlsx chat files using the backend-parsed
// per-sheet CSV payload (`/api/chat/file/{id}?parsed=true`) instead of
// attempting to decode the raw binary xlsx bytes as text.
import React, { useState, useEffect } from "react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ContentComponentProps } from "./ExpandableContentWrapper";
import { parseCSV } from "./CSVContent";
import { SvgAlertCircle, SvgSimpleLoader } from "@opal/icons";
import { Button, Text } from "@opal/components";
import { cn } from "@opal/utils";
import { fetchChatFile } from "@/lib/chat/svc";

export interface SpreadsheetSheet {
  name: string;
  csv: string;
  truncated: boolean;
}

export interface SpreadsheetPreviewData {
  sheets: SpreadsheetSheet[];
}

const SPREADSHEET_EXTENSIONS = [".xlsx", ".xlsm"];

export function isSpreadsheetFileName(
  fileName: string | null | undefined
): boolean {
  if (!fileName) return false;
  const lowered = fileName.toLowerCase();
  return SPREADSHEET_EXTENSIONS.some((ext) => lowered.endsWith(ext));
}

export function parseSpreadsheetPreview(
  jsonText: string
): SpreadsheetPreviewData | null {
  try {
    const parsed: unknown = JSON.parse(jsonText);
    if (
      typeof parsed !== "object" ||
      parsed === null ||
      !Array.isArray((parsed as SpreadsheetPreviewData).sheets)
    ) {
      return null;
    }
    return parsed as SpreadsheetPreviewData;
  } catch {
    return null;
  }
}

interface SheetTableProps {
  sheet: SpreadsheetSheet;
}

function SheetTable({ sheet }: SheetTableProps) {
  let rows: string[][] = [];
  try {
    rows = parseCSV(sheet.csv.trim());
  } catch {
    rows = [];
  }
  const headers = rows[0];

  if (!headers || headers.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-8">
        <Text as="p" font="main-ui-body" color="text-03">
          This sheet is empty.
        </Text>
      </div>
    );
  }

  return (
    <Table>
      <TableHeader className="sticky top-0 z-sticky">
        <TableRow className="bg-background-tint-01">
          {headers.map((header, index) => (
            <TableHead key={index}>
              <Text as="p" maxLines={2} font="main-ui-action" color="text-03">
                {header}
              </Text>
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>

      <TableBody>
        {rows.slice(1).map((row, rowIndex) => (
          <TableRow key={rowIndex}>
            {headers.map((_, cellIndex) => (
              <TableCell
                className={cn(
                  cellIndex === 0 && "sticky left-0 bg-background-tint-01",
                  "py-0 px-4"
                )}
                key={cellIndex}
              >
                {row[cellIndex] ?? ""}
              </TableCell>
            ))}
          </TableRow>
        ))}
        {sheet.truncated && (
          <TableRow>
            <TableCell colSpan={headers.length} className="py-2 px-4">
              <Text as="p" font="secondary-body" color="text-04">
                Preview truncated — download the file to see all rows.
              </Text>
            </TableCell>
          </TableRow>
        )}
      </TableBody>
    </Table>
  );
}

interface SpreadsheetSheetsViewProps {
  sheets: SpreadsheetSheet[];
  className?: string;
}

export function SpreadsheetSheetsView({
  sheets,
  className,
}: SpreadsheetSheetsViewProps) {
  const [activeSheetIndex, setActiveSheetIndex] = useState(0);
  const activeSheet = sheets[activeSheetIndex] ?? sheets[0];

  if (!activeSheet) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-8">
        <SvgAlertCircle className="w-8 h-8 stroke-error" />
        <Text as="p" font="main-ui-body" color="text-03">
          Unable to preview this spreadsheet.
        </Text>
      </div>
    );
  }

  return (
    <div className={cn("flex flex-col w-full", className)}>
      {sheets.length > 1 && (
        <div className="flex flex-row gap-1 p-2 overflow-x-auto shrink-0">
          {sheets.map((sheet, index) => (
            <Button
              key={index}
              size="sm"
              prominence={index === activeSheetIndex ? "secondary" : "tertiary"}
              onClick={() => setActiveSheetIndex(index)}
            >
              {sheet.name}
            </Button>
          ))}
        </div>
      )}
      <div className="flex relative min-h-0 overflow-auto">
        <SheetTable sheet={activeSheet} />
      </div>
    </div>
  );
}

function SpreadsheetContent({
  fileDescriptor,
  expanded = false,
}: ContentComponentProps) {
  const [sheets, setSheets] = useState<SpreadsheetSheet[] | null>(null);
  const [isFetching, setIsFetching] = useState(true);

  // Cache parsed sheets across mounts so closing other modals doesn't force a
  // refetch. Keyed by file id; safe because chat file ids are unique.
  const cacheKey = fileDescriptor.id;

  useEffect(() => {
    const cached = spreadsheetCache.get(cacheKey);
    if (cached) {
      setSheets(cached);
      setIsFetching(false);
      return;
    }

    let cancelled = false;
    const fetchSheets = async () => {
      setIsFetching(true);
      try {
        const response = await fetchChatFile(cacheKey, true);
        const preview = parseSpreadsheetPreview(await response.text());
        if (!preview) {
          throw new Error("Failed to parse spreadsheet preview");
        }
        if (!cancelled) {
          setSheets(preview.sheets);
          spreadsheetCache.set(cacheKey, preview.sheets);
        }
      } catch (error) {
        console.error("Error fetching spreadsheet preview:", error);
        if (!cancelled) {
          setSheets(null);
        }
      } finally {
        if (!cancelled) {
          setIsFetching(false);
        }
      }
    };
    fetchSheets();
    return () => {
      cancelled = true;
    };
  }, [cacheKey]);

  if (isFetching) {
    return (
      <div className="flex items-center justify-center h-[300px]">
        <SvgSimpleLoader />
      </div>
    );
  }

  if (!sheets || sheets.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-8">
        <SvgAlertCircle className="w-8 h-8 stroke-error" />
        <Text as="p" font="main-ui-body" color="text-03">
          Error loading spreadsheet
        </Text>
        <Text as="p" font="main-ui-body" color="text-04">
          The spreadsheet may be corrupted or couldn&apos;t be loaded properly.
        </Text>
      </div>
    );
  }

  return (
    <SpreadsheetSheetsView
      sheets={sheets}
      className={expanded ? "max-h-[600px]" : "max-h-[300px]"}
    />
  );
}

export default SpreadsheetContent;

const spreadsheetCache = new Map<string, SpreadsheetSheet[]>();
