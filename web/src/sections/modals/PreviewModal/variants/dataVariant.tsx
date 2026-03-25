import Text from "@/refresh-components/texts/Text";
import { Section } from "@/layouts/general-layouts";
import { getDataLanguage, getLanguageByMime } from "@/lib/languages";
import { PreviewVariant } from "@/sections/modals/PreviewModal/interfaces";
import { CodePreview } from "@/sections/modals/PreviewModal/variants/CodePreview";
import {
  CopyButton,
  DownloadButton,
} from "@/sections/modals/PreviewModal/variants/shared";

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
      ? `${ctx.language} - ${ctx.lineCount} ${
          ctx.lineCount === 1 ? "line" : "lines"
        } · ${ctx.fileSize}`
      : "",

  renderContent: (ctx) => {
    const formatted = formatContent(ctx.language, ctx.fileContent);
    return (
      <CodePreview normalize content={formatted} language={ctx.language} />
    );
  },

  renderFooterLeft: (ctx) => (
    <Text text03 mainUiBody className="select-none">
      {ctx.lineCount} {ctx.lineCount === 1 ? "line" : "lines"}
    </Text>
  ),

  renderFooterRight: (ctx) => (
    <Section flexDirection="row" width="fit">
      <CopyButton getText={() => ctx.fileContent} />
      <DownloadButton fileUrl={ctx.fileUrl} fileName={ctx.fileName} />
    </Section>
  ),
};
