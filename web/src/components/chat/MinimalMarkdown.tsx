import { AnswerCodeBlock, InlineCode } from "@/lib/answerText/codeBlocks";
import {
  MemoizedLink,
  MemoizedParagraph,
} from "@/lib/timeline/chat/message/MemoizedTextComponents";
import { useMemo, CSSProperties } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import type { PluggableList } from "unified";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import { transformLinkUri } from "@/lib/utils";
import { rehypeDirection } from "@/lib/rehypeDirection";
import { cn } from "@opal/utils";

type MinimalMarkdownComponentOverrides = Partial<Components>;

interface MinimalMarkdownProps {
  content: string;
  className?: string;
  /**
   * Override specific markdown renderers.
   * Any renderer not provided will fall back to this component's defaults.
   */
  components?: MinimalMarkdownComponentOverrides;
}

const REHYPE_PLUGINS: PluggableList = [rehypeKatex, rehypeDirection];

export default function MinimalMarkdown({
  content,
  className = "",
  components,
}: MinimalMarkdownProps) {
  const markdownComponents = useMemo(() => {
    const defaults: Components = {
      a: MemoizedLink,
      p: ({ dir, children }) => (
        <MemoizedParagraph dir={dir}>{children}</MemoizedParagraph>
      ),
      // A caller's own `code` renderer also renders fenced code.
      pre: components?.code
        ? ({ children }) => <>{children}</>
        : AnswerCodeBlock,
      code: InlineCode,
    };

    return {
      ...defaults,
      ...components,
    } satisfies Components;
  }, [components]);

  return (
    // dir="auto" backstops component overrides that do not forward the
    // per-block dir stamped by rehypeDirection.
    <div dir="auto">
      <ReactMarkdown
        className={cn(
          "prose dark:prose-invert max-w-full text-sm wrap-break-word",
          className
        )}
        components={markdownComponents}
        rehypePlugins={REHYPE_PLUGINS}
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
