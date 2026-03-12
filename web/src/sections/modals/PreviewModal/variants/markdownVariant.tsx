import { Section } from "@/layouts/general-layouts";
import { isMarkdownFile } from "@/lib/languages";
import { PreviewVariant } from "@/sections/modals/PreviewModal/interfaces";
import { CodePreview } from "@/sections/modals/PreviewModal/variants/CodePreview";
import {
  CopyButton,
  DownloadButton,
} from "@/sections/modals/PreviewModal/variants/shared";

const MARKDOWN_MIMES = [
  "text/markdown",
  "text/x-markdown",
  "text/x-rst",
  "text/x-org",
];

export const markdownVariant: PreviewVariant = {
  matches: (name, mime) => {
    if (MARKDOWN_MIMES.some((m) => mime.startsWith(m))) return true;
    return isMarkdownFile(name || "");
  },
  width: "lg",
  height: "full",
  needsTextContent: true,
  codeBackground: false,
  headerDescription: () => "",

  renderContent: (ctx) => (
    <CodePreview content={ctx.fileContent} language={ctx.language} />
  ),

  renderFooterLeft: () => null,

  renderFooterRight: (ctx) => (
    <Section flexDirection="row" width="fit">
      <CopyButton getText={() => ctx.fileContent} />
      <DownloadButton fileUrl={ctx.fileUrl} fileName={ctx.fileName} />
    </Section>
  ),
};
