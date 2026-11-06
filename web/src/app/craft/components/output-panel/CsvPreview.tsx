"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";
import { Text } from "@opal/components";
import { SpreadsheetTable } from "@/app/craft/components/output-panel/SpreadsheetTable";

import {
  FilePreviewScrollArea,
  type FilePreviewScrollPosition,
} from "@/app/craft/components/output-panel/FilePreviewScrollArea";

import { parseCsv, SPREADSHEET_PREVIEW_LIMITS } from "@/lib/csv";

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
      return {
        result: parseCsv(content, SPREADSHEET_PREVIEW_LIMITS),
        error: false,
      };
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
            rows: SPREADSHEET_PREVIEW_LIMITS.maxRows,
            columns: SPREADSHEET_PREVIEW_LIMITS.maxColumns,
            cells: SPREADSHEET_PREVIEW_LIMITS.maxCells,
          })}
        </Text>
      )}
      <SpreadsheetTable rows={rows} />
    </FilePreviewScrollArea>
  );
}
