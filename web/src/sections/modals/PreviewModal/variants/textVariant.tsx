import Text from "@/refresh-components/texts/Text";
import { Section } from "@/layouts/general-layouts";
import { PreviewVariant } from "@/sections/modals/PreviewModal/interfaces";
import { CodePreview } from "@/sections/modals/PreviewModal/variants/CodePreview";
import {
  CopyButton,
  DownloadButton,
} from "@/sections/modals/PreviewModal/variants/shared";

const TEXT_MIMES = [
  "text/plain",
  "text/x-log",
  "text/x-config",
  "text/tab-separated-values",
];

const TEXT_EXTENSIONS = [".txt", ".log", ".conf", ".sql", ".tsv"];

export const textVariant: PreviewVariant = {
  matches: (name, mime) => {
    if (TEXT_MIMES.some((supportedMime) => mime.startsWith(supportedMime))) {
      return true;
    }

    const lowerName = (name || "").toLowerCase();
    return TEXT_EXTENSIONS.some((extension) => lowerName.endsWith(extension));
  },
  width: "md",
  height: "lg",
  needsTextContent: true,
  headerDescription: (ctx) =>
    ctx.fileContent
      ? `${ctx.lineCount} ${ctx.lineCount === 1 ? "line" : "lines"} · ${
          ctx.fileSize
        }`
      : "",

  renderContent: (ctx) => (
    <CodePreview content={ctx.fileContent} language={ctx.language} />
  ),

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
