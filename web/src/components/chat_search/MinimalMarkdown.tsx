import { CodeBlock } from "@/app/chat/message/CodeBlock";
import { extractCodeText } from "@/app/chat/message/codeUtils";
import {
  MemoizedLink,
  MemoizedParagraph,
} from "@/app/chat/message/MemoizedTextComponents";
import React, { useMemo } from "react";
import ReactMarkdown from "react-markdown";
import rehypePrism from "rehype-prism-plus";
import remarkGfm from "remark-gfm";

interface MinimalMarkdownProps {
  content: string;
  className?: string;
}

export const MinimalMarkdown: React.FC<MinimalMarkdownProps> = ({
  content,
  className = "",
}) => {
  const markdownComponents = useMemo(
    () => ({
      a: MemoizedLink,
      p: MemoizedParagraph,
      code: ({ node, inline, className, children, ...props }: any) => {
        const codeText = extractCodeText(node, content, children);
        return (
          <CodeBlock className={className} codeText={codeText}>
            {children}
          </CodeBlock>
        );
      },
    }),
    [content]
  );

  return (
    <ReactMarkdown
      className={`prose max-w-full text-base ${className}`}
      components={markdownComponents}
      remarkPlugins={[remarkGfm]}
      rehypePlugins={[[rehypePrism, { ignoreMissing: true }]]}
    >
      {content}
    </ReactMarkdown>
  );
};
