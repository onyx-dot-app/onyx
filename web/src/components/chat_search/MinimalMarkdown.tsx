import { CodeBlock } from "@/app/chat/message/CodeBlock";
import { extractCodeText } from "@/app/chat/message/codeUtils";
import {
  MemoizedLink,
  MemoizedParagraph,
} from "@/app/chat/message/MemoizedTextComponents";
import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface MinimalMarkdownProps {
  content: string;
  className?: string;
}

export const MinimalMarkdown: React.FC<MinimalMarkdownProps> = ({
  content,
  className = "",
}) => {
  return (
    <ReactMarkdown
      className={`w-full text-wrap break-word ${className}`}
      components={{
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
      }}
      remarkPlugins={[remarkGfm]}
    >
      {content}
    </ReactMarkdown>
  );
};
