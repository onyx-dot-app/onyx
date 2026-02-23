import MinimalMarkdown from "@/components/chat/MinimalMarkdown";
import Text from "@/refresh-components/texts/Text";
import { Section } from "@/layouts/general-layouts";
import { getCodeLanguage } from "@/lib/languages";
import { CodeBlock } from "@/app/app/message/CodeBlock";
import { extractCodeText } from "@/app/app/message/codeUtils";
import { PreviewVariant } from "@/sections/modals/PreviewModal/interfaces";
import {
  CopyButton,
  DownloadButton,
} from "@/sections/modals/PreviewModal/variants/shared";

export const codeVariant: PreviewVariant = {
  matches: (name) => !!getCodeLanguage(name || ""),
  width: "md",
  height: "lg",
  needsTextContent: true,

  headerDescription: (ctx) =>
    ctx.fileContent
      ? `${ctx.language} - ${ctx.lineCount} ${
          ctx.lineCount === 1 ? "line" : "lines"
        } · ${ctx.fileSize}`
      : "",

  renderContent: (ctx) => (
    <MinimalMarkdown
      content={`\`\`\`${ctx.language}\n${ctx.fileContent}\n\n\`\`\``}
      className="w-full break-words h-full"
      components={{
        code: ({ node, children }: any) => {
          const codeText = extractCodeText(node, ctx.fileContent, children);
          return (
            <CodeBlock className="" codeText={codeText}>
              {children}
            </CodeBlock>
          );
        },
      }}
    />
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
