import { Section } from "@/layouts/general-layouts";
import { PreviewVariant } from "@/sections/modals/PreviewModal/interfaces";
import { DownloadButton } from "@/sections/modals/PreviewModal/variants/shared";
import {
  isSpreadsheetFileName,
  parseSpreadsheetPreview,
  SpreadsheetSheetsView,
} from "@/components/tools/SpreadsheetContent";
import { Text } from "@opal/components";

const SPREADSHEET_MIME_TYPES = [
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  "application/vnd.ms-excel.sheet.macroenabled.12",
];

function isSpreadsheetMimeType(mime: string): boolean {
  const normalized = mime.split(";")[0]?.trim().toLowerCase() ?? "";
  return SPREADSHEET_MIME_TYPES.includes(normalized);
}

export const xlsxVariant: PreviewVariant = {
  matches: (name, mime) =>
    isSpreadsheetMimeType(mime) || isSpreadsheetFileName(name),
  width: "full",
  height: "full",
  needsTextContent: false,
  needsParsedContent: true,
  codeBackground: false,

  headerDescription: (ctx) => {
    const preview = parseSpreadsheetPreview(ctx.fileContent);
    if (!preview) return "";
    return ctx.t("xlsx.headerDescription", { count: preview.sheets.length });
  },

  renderContent: (ctx) => {
    const preview = parseSpreadsheetPreview(ctx.fileContent);
    if (!preview || preview.sheets.length === 0) {
      return (
        <Section padding={4}>
          <Text as="p" font="main-ui-body" color="text-03">
            {ctx.t("xlsx.parseError.message")}
          </Text>
        </Section>
      );
    }
    return (
      <SpreadsheetSheetsView
        sheets={preview.sheets}
        className="flex-1 min-h-0 p-1"
      />
    );
  },

  renderFooterLeft: (ctx) => {
    const preview = parseSpreadsheetPreview(ctx.fileContent);
    if (!preview) return null;
    return (
      <Text font="main-ui-body" color="text-03">
        {ctx.t("xlsx.sheetCount", { count: preview.sheets.length })}
      </Text>
    );
  },
  renderFooterRight: (ctx) => (
    <DownloadButton fileUrl={ctx.fileUrl} fileName={ctx.fileName} />
  ),
};
