import { CodeBlock } from "@/app/chat/message/CodeBlock";
import { extractCodeText } from "@/app/chat/message/codeUtils";
import {
  MemoizedLink,
  MemoizedParagraph,
} from "@/app/chat/message/MemoizedTextComponents";
import React, { useMemo, CSSProperties } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypePrism from "rehype-prism-plus";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import { transformLinkUri } from "@/lib/utils";

interface MinimalMarkdownProps {
  content: string;
  className?: string;
  style?: CSSProperties;
}

export default function MinimalMarkdown({
  content,
  className = "",
  style,
}: MinimalMarkdownProps) {
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
    <div style={style || {}} className={`${className}`}>
      <ReactMarkdown
        className="prose dark:prose-invert max-w-full text-sm break-words"
        components={markdownComponents}
        rehypePlugins={[[rehypePrism, { ignoreMissing: true }], rehypeKatex]}
        remarkPlugins={[
          remarkGfm,
          [remarkMath, { singleDollarTextMath: false }],
        ]}
        urlTransform={transformLinkUri}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
