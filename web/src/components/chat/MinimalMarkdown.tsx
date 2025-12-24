import { CodeBlock } from "@/app/chat/message/CodeBlock";
import { extractCodeText } from "@/app/chat/message/codeUtils";
import {
  MemoizedLink,
  MemoizedParagraph,
} from "@/app/chat/message/MemoizedTextComponents";
import React, { useMemo, CSSProperties } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import { transformLinkUri } from "@/lib/utils";

type MinimalMarkdownComponentOverrides = Partial<Components>;

interface MinimalMarkdownProps {
  content: string;
  className?: string;
  style?: CSSProperties;
  /**
   * Override specific markdown renderers.
   * Any renderer not provided will fall back to this component's defaults.
   */
  components?: MinimalMarkdownComponentOverrides;
}

export default function MinimalMarkdown({
  content,
  className = "",
  style,
  components,
}: MinimalMarkdownProps) {
  const markdownComponents = useMemo(() => {
    const defaults: Components = {
      a: MemoizedLink,
      p: MemoizedParagraph,
      pre: ({ node, className, children }: any) => {
        // Don't render the pre wrapper - CodeBlock handles its own wrapper
        return <>{children}</>;
      },
      code: ({ node, inline, className, children, ...props }: any) => {
        const codeText = extractCodeText(node, content, children);
        return (
          <CodeBlock className={className} codeText={codeText}>
            {children}
          </CodeBlock>
        );
      },
    };

    return {
      ...defaults,
      ...(components ?? {}),
    } satisfies Components;
  }, [content, components]);

  return (
    <div style={style || {}} className={`${className}`}>
      <ReactMarkdown
        className="prose dark:prose-invert max-w-full text-sm break-words"
        components={markdownComponents}
        rehypePlugins={[rehypeHighlight, rehypeKatex]}
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
