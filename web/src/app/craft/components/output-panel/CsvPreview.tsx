"use client";

import { memo, useMemo } from "react";
import { useTranslations } from "next-intl";
import { Text } from "@opal/components";

import { FilePreviewScrollArea } from "@/app/craft/components/output-panel/FilePreviewScrollArea";

import type { FilePreviewScrollPosition } from "@/app/craft/components/output-panel/types";
import { parseCsv } from "@/lib/csv";

const PREVIEW_LIMITS = {
  maxRows: 1000,
  maxColumns: 100,
  maxCharacters: 2_000_000,
  maxCells: 5000,
};

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
  const parsed = useMemo(() => {
    try {
      return { result: parseCsv(content, PREVIEW_LIMITS), error: false };
    } catch {
      return { result: { rows: [], truncated: false }, error: true };
    }
  }, [content]);
  const { rows, truncated } = parsed.result;
  return (
    <FilePreviewScrollArea
      initialScrollTop={initialScrollTop}
      onScrollTopChange={onScrollTopChange}
      isActive={isActive}
      padding={0}
      paddingX={4}
    >
      {parsed.error && (
        <div role="alert">
          <Text font="secondary-body" color="text-03">
            {t("csv.malformed")}
          </Text>
        </div>
      )}
      {truncated && (
        <Text font="secondary-body" color="text-03">
          {t("csv.truncated", {
            rows: PREVIEW_LIMITS.maxRows,
            columns: PREVIEW_LIMITS.maxColumns,
            cells: PREVIEW_LIMITS.maxCells,
          })}
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
