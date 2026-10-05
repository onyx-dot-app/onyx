import { Text, CopyButton } from "@opal/components";
import { Section } from "@/layouts/general-layouts";
import { getDataLanguage, getLanguageByMime } from "@/lib/languages";
import { PreviewVariant } from "@/sections/modals/PreviewModal/interfaces";
import { CodePreview } from "@/sections/modals/PreviewModal/variants/CodePreview";
import { DownloadButton } from "@/sections/modals/PreviewModal/variants/shared";

function formatContent(language: string, content: string): string {
  if (language === "json") {
    try {
      return JSON.stringify(JSON.parse(content), null, 2);
    } catch {
      return content;
    }
  }
  return content;
}

export const dataVariant: PreviewVariant = {
  matches: (name, mime) =>
    !!getDataLanguage(name || "") || !!getLanguageByMime(mime),
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

  renderContent: (ctx) => {
    const formatted = formatContent(ctx.language, ctx.fileContent);
    return (
      <CodePreview normalize content={formatted} language={ctx.language} />
    );
  },

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
