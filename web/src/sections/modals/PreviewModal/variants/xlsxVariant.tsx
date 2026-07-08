import { Section } from "@/layouts/general-layouts";
import { PreviewVariant } from "@/sections/modals/PreviewModal/interfaces";
import { DownloadButton } from "@/sections/modals/PreviewModal/variants/shared";
import {
  isSpreadsheetFileName,
  parseSpreadsheetPreview,
  SpreadsheetSheetsView,
} from "@/components/tools/SpreadsheetContent";
import { Text } from "@opal/components";

const SPREADSHEET_MIME_TYPE =
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

export const xlsxVariant: PreviewVariant = {
  matches: (name, mime) =>
    mime === SPREADSHEET_MIME_TYPE || isSpreadsheetFileName(name),
  width: "full",
  height: "full",
  needsTextContent: false,
  needsParsedContent: true,
  codeBackground: false,

  headerDescription: (ctx) => {
    const preview = parseSpreadsheetPreview(ctx.fileContent);
    if (!preview) return "";
    const count = preview.sheets.length;
    return `Spreadsheet - ${count} ${count === 1 ? "sheet" : "sheets"}`;
  },

  renderContent: (ctx) => {
    const preview = parseSpreadsheetPreview(ctx.fileContent);
    if (!preview || preview.sheets.length === 0) {
      return (
        <Section padding={1}>
          <Text as="p" font="main-ui-body" color="text-03">
            Unable to preview this spreadsheet.
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
    const count = preview.sheets.length;
    return (
      <Text font="main-ui-body" color="text-03">
        {`${count} ${count === 1 ? "sheet" : "sheets"}`}
      </Text>
    );
  },
  renderFooterRight: (ctx) => (
    <DownloadButton fileUrl={ctx.fileUrl} fileName={ctx.fileName} />
  ),
};
