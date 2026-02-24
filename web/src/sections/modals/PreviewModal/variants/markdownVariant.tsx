import MinimalMarkdown from "@/components/chat/MinimalMarkdown";
import ScrollIndicatorDiv from "@/refresh-components/ScrollIndicatorDiv";
import { Section } from "@/layouts/general-layouts";
import { PreviewVariant } from "@/sections/modals/PreviewModal/interfaces";
import {
  CopyButton,
  DownloadButton,
} from "@/sections/modals/PreviewModal/variants/shared";

const MARKDOWN_MIMES = [
  "text/markdown",
  "text/x-markdown",
  "text/plain",
  "text/x-rst",
  "text/x-org",
];

export const markdownVariant: PreviewVariant = {
  matches: (name, mime) => {
    if (MARKDOWN_MIMES.some((m) => mime.startsWith(m))) return true;
    const lower = (name || "").toLowerCase();
    return (
      lower.endsWith(".md") ||
      lower.endsWith(".markdown") ||
      lower.endsWith(".txt") ||
      lower.endsWith(".rst") ||
      lower.endsWith(".org")
    );
  },
  width: "lg",
  height: "full",
  needsTextContent: true,
  headerDescription: () => "",

  renderContent: (ctx) => (
    <ScrollIndicatorDiv className="flex-1 min-h-0 p-4" variant="shadow">
      <MinimalMarkdown
        content={ctx.fileContent}
        className="w-full pb-4 h-full text-lg break-words"
      />
    </ScrollIndicatorDiv>
  ),

  renderFooterLeft: () => null,

  renderFooterRight: (ctx) => (
    <Section flexDirection="row" width="fit">
      <CopyButton getText={() => ctx.fileContent} />
      <DownloadButton fileUrl={ctx.fileUrl} fileName={ctx.fileName} />
    </Section>
  ),
};
