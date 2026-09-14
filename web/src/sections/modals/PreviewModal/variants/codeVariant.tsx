import { Text, CopyButton } from "@opal/components";
import { Section } from "@/layouts/general-layouts";
import { getCodeLanguage } from "@/lib/languages";
import { PreviewVariant } from "@/sections/modals/PreviewModal/interfaces";
import { CodePreview } from "@/sections/modals/PreviewModal/variants/CodePreview";
import { DownloadButton } from "@/sections/modals/PreviewModal/variants/shared";

export const codeVariant: PreviewVariant = {
  matches: (name) => !!getCodeLanguage(name || ""),
  width: "xl",
  height: "lg",
  needsTextContent: true,
  codeBackground: true,

  headerDescription: (ctx) =>
    ctx.fileContent
      ? ctx.t("code.headerDescription", {
          fileSize: ctx.fileSize,
          language: ctx.language,
          lineCount: ctx.lineCount,
        })
      : "",

  renderContent: (ctx) => (
    <CodePreview normalize content={ctx.fileContent} language={ctx.language} />
  ),

  renderFooterLeft: (ctx) => (
    <Text font="main-ui-body" color="text-03">
      {ctx.t("lineCount.label", { count: ctx.lineCount })}
    </Text>
  ),

  renderFooterRight: (ctx) => (
    <Section flexDirection="row" width="fit">
      <CopyButton
        size="sm"
        tooltip={ctx.t("copyButton.tooltip")}
        getCopyText={() => ctx.fileContent}
      />
      <DownloadButton fileUrl={ctx.fileUrl} fileName={ctx.fileName} />
    </Section>
  ),
};
