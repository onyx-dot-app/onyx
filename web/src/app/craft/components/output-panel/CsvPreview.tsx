"use client";

import { memo, useMemo } from "react";
import { useTranslations } from "next-intl";
import { Text } from "@opal/components";

import {
  FilePreviewScrollArea,
  type FilePreviewScrollPosition,
} from "@/app/craft/components/output-panel/FilePreviewScrollArea";

const MAX_ROWS = 1000;
const MAX_COLUMNS = 100;
const MAX_CHARACTERS = 2_000_000;

interface CsvParseResult {
  rows: string[][];
  truncated: boolean;
}

/** Parses RFC 4180 cells, including quoted newlines, with bounded work. */
export function parseCsv(content: string): CsvParseResult {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;
  let truncated = content.length > MAX_CHARACTERS;
  const source = content.slice(0, MAX_CHARACTERS).replace(/^\uFEFF/, "");
  for (let index = 0; index < source.length; index++) {
    const char = source[index];
    if (char === '"') {
      if (quoted && source[index + 1] === '"') {
        cell += '"';
        index++;
      } else if (quoted || cell === "") quoted = !quoted;
      else cell += char;
    } else if (!quoted && (char === "," || char === "\n" || char === "\r")) {
      if (row.length < MAX_COLUMNS) row.push(cell);
      else truncated = true;
      cell = "";
      if (char !== ",") {
        if (char === "\r" && source[index + 1] === "\n") index++;
        rows.push(row);
        row = [];
        if (rows.length >= MAX_ROWS)
          return { rows, truncated: index < source.length - 1 || truncated };
      }
    } else cell += char;
  }
  if (cell || row.length || (source.length > 0 && !/[\r\n]$/.test(source))) {
    if (row.length < MAX_COLUMNS) row.push(cell);
    else truncated = true;
    rows.push(row);
  }
  return { rows, truncated };
}

interface CsvPreviewProps extends FilePreviewScrollPosition {
  content: string;
}

export function CsvPreview({
  content,
  initialScrollTop,
  onScrollTopChange,
  isActive,
}: CsvPreviewProps) {
  const t = useTranslations("craft.filePreview");
  const { rows, truncated } = useMemo(() => parseCsv(content), [content]);
  return (
    <FilePreviewScrollArea
      initialScrollTop={initialScrollTop}
      onScrollTopChange={onScrollTopChange}
      isActive={isActive}
      padding={0}
      paddingX={4}
    >
      {truncated && (
        <Text font="secondary-body" color="text-03">
          {t("csv.truncated")}
        </Text>
      )}
      <CsvTable rows={rows} />
    </FilePreviewScrollArea>
  );
}

function CsvTableView({ rows }: { rows: string[][] }) {
  return (
    <table className="text-sm text-text-04 border-collapse">
      <thead className="sticky top-0 z-10 bg-background-neutral-01">
        <tr>
          {rows[0]?.map((cell, index) => (
            <th
              key={index}
              className="text-start font-medium px-3 py-2 border-b border-border-01 whitespace-pre-wrap"
            >
              <Text font="secondary-action" color="text-04">
                {cell}
              </Text>
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.slice(1).map((row, index) => (
          <tr key={index}>
            {row.map((cell, column) => (
              <td
                key={column}
                className="px-3 py-2 border-b border-border-01 whitespace-pre-wrap"
              >
                <Text font="secondary-body" color="text-04">
                  {cell}
                </Text>
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

const CsvTable = memo(CsvTableView);
