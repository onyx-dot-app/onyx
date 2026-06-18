import { CodeBlock } from "@/app/app/message/CodeBlock";
import { extractCodeText } from "@/app/app/message/codeUtils";
import {
  MemoizedLink,
  MemoizedParagraph,
} from "@/app/app/message/MemoizedTextComponents";
import { useMemo, CSSProperties } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import type { PluggableList } from "unified";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import { transformLinkUri } from "@/lib/utils";
import { cn } from "@opal/utils";

type MinimalMarkdownComponentOverrides = Partial<Components>;

interface MinimalMarkdownProps {
  content: string;
  className?: string;
  showHeader?: boolean;
  /**
   * Override specific markdown renderers.
   * Any renderer not provided will fall back to this component's defaults.
   */
  components?: MinimalMarkdownComponentOverrides;
  /** Skip rehype-highlight while content is mid-stream. Flip false on completion. */
  streaming?: boolean;
}

export default function MinimalMarkdown({
  content,
  className = "",
  showHeader = true,
  components,
  streaming = false,
}: MinimalMarkdownProps) {
  const rehypePlugins = useMemo<PluggableList>(
    () =>
      streaming
        ? [rehypeKatex]
        : [[rehypeHighlight, { detect: true }], rehypeKatex],
    [streaming]
  );
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
          <CodeBlock
            className={className}
            codeText={codeText}
            showHeader={showHeader}
          >
            {children}
          </CodeBlock>
        );
      },
    };

    return {
      ...defaults,
      ...components,
    } satisfies Components;
  }, [content, components, showHeader]);

  return (
    <ReactMarkdown
      className={cn(
        "prose dark:prose-invert max-w-full text-sm wrap-break-word",
        className
      )}
      components={markdownComponents}
      rehypePlugins={rehypePlugins}
      remarkPlugins={[remarkGfm, [remarkMath, { singleDollarTextMath: false }]]}
      urlTransform={transformLinkUri}
    >
      {content}
    </ReactMarkdown>
  );
}
