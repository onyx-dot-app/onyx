"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import { SpreadsheetTable } from "@/app/craft/components/output-panel/SpreadsheetTable";
import { SPREADSHEET_PREVIEW_LIMITS } from "@/lib/csv";
import {
  FilePreviewScrollArea,
  type FilePreviewScrollPosition,
} from "@/app/craft/components/output-panel/FilePreviewScrollArea";
import type { ParsedSpreadsheetSheet } from "@/lib/spreadsheetPreview";

interface SpreadsheetPreviewProps extends FilePreviewScrollPosition {
  sheets: ParsedSpreadsheetSheet[];
}

export default function SpreadsheetPreview({
  sheets,
  ...scroll
}: SpreadsheetPreviewProps) {
  const t = useTranslations("craft.filePreview");
  const [selected, setSelected] = useState(sheets[0]?.name);
  const sheet = sheets.find(({ name }) => name === selected) ?? sheets[0];
  return (
    <Section
      gap={0}
      padding={4}
      alignItems="stretch"
      justifyContent="start"
      className="min-h-0"
    >
      <Section
        gap={0}
        alignItems="stretch"
        justifyContent="start"
        className="min-h-0 overflow-hidden rounded-lg border border-border-01 bg-background-neutral-01"
      >
        <Section
          gap={0}
          alignItems="stretch"
          justifyContent="start"
          className="min-h-0 flex-1"
        >
          <FilePreviewScrollArea key={sheet?.name} padding={0} {...scroll}>
            {sheet?.truncated && (
              <Section height="auto" alignItems="start" padding={2}>
                <Text font="secondary-body" color="text-03">
                  {t("csv.truncated", {
                    rows: SPREADSHEET_PREVIEW_LIMITS.maxRows,
                    columns: SPREADSHEET_PREVIEW_LIMITS.maxColumns,
                    cells: SPREADSHEET_PREVIEW_LIMITS.maxCells,
                  })}
                </Text>
              </Section>
            )}
            {sheet?.rows.length ? (
              <SpreadsheetTable rows={sheet.rows} framed={false} />
            ) : (
              <Text font="secondary-body" color="text-03">
                {t("noContent.label")}
              </Text>
            )}
          </FilePreviewScrollArea>
        </Section>
        <Section
          height="auto"
          padding={3}
          flexDirection="row"
          justifyContent="start"
          gap={1}
          className="shrink-0 overflow-x-auto border-t border-border-01 bg-background-neutral-02"
        >
          {sheets.map(({ name }) => (
            <Button
              key={name}
              size="md"
              prominence={name === sheet?.name ? "primary" : "tertiary"}
              aria-pressed={name === sheet?.name}
              onClick={() => setSelected(name)}
            >
              {name}
            </Button>
          ))}
        </Section>
      </Section>
    </Section>
  );
}
