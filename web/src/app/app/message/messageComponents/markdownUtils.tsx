import React, { useCallback, useEffect, useRef, useMemo, JSX } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeHighlight from "rehype-highlight";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import "@/app/app/message/custom-code-styles.css";
import { FullChatState } from "@/app/app/message/messageComponents/interfaces";
import {
  MemoizedAnchor,
  MemoizedParagraph,
} from "@/app/app/message/MemoizedTextComponents";
import {
  extractCodeText,
  preprocessLaTeX,
  escapeIncompleteBlockMath,
  escapeIncompleteInlineMath,
} from "@/app/app/message/codeUtils";
import { CodeBlock } from "@/app/app/message/CodeBlock";
import { transformLinkUri } from "@/lib/utils";
import { cn } from "@opal/utils";
import { InMessageImage } from "@/app/app/components/files/images/InMessageImage";
import { extractChatImageFileId } from "@/app/app/components/files/images/utils";

/** Table wrapper that detects horizontal overflow and shows a fade + scrollbar. */
interface ScrollableTableProps
  extends React.TableHTMLAttributes<HTMLTableElement> {
  children: React.ReactNode;
}

export function ScrollableTable({
  className,
  children,
  ...props
}: ScrollableTableProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const tableRef = useRef<HTMLTableElement>(null);

  useEffect(() => {
    const el = scrollRef.current;
    const wrap = wrapRef.current;
    const table = tableRef.current;
    if (!el || !wrap) return;

    const check = () => {
      const overflows = el.scrollWidth > el.clientWidth;
      const atEnd = el.scrollLeft + el.clientWidth >= el.scrollWidth - 2;
      wrap.dataset.overflows = overflows && !atEnd ? "true" : "false";
      el.dataset.scrolled = el.scrollLeft > 0 ? "true" : "false";
    };

    check();
    el.addEventListener("scroll", check, { passive: true });
    // Observe both the scroll container (parent resize) and the table
    // itself (content growth during streaming).
    const ro = new ResizeObserver(check);
    ro.observe(el);
    if (table) ro.observe(table);

    return () => {
      el.removeEventListener("scroll", check);
      ro.disconnect();
    };
  }, []);

  return (
    <div ref={wrapRef} className="markdown-table-card">
      <div ref={scrollRef} className="markdown-table-breakout">
        <table
          ref={tableRef}
          className={cn(
            className,
            "min-w-full !my-0 [&_th]:whitespace-nowrap [&_td]:whitespace-nowrap"
          )}
          {...props}
        >
          {children}
        </table>
      </div>
    </div>
  );
}

/**
 * Processes content for markdown rendering by handling code blocks and LaTeX
 */
export const processContent = (content: string): string => {
  // Strip incomplete citation links at the end of streaming content.
  // During typewriter animation, [[N]](url) is revealed character by character.
  // ReactMarkdown can't parse an incomplete link and renders it as raw text.
  // This regex removes any trailing partial citation pattern so only complete
  // links are passed to the markdown parser.
  content = content.replace(/\[\[\d+\]\]\([^)]*$/, "");
  // Also strip a lone [[ or [[N] or [[N]] at the very end (before the URL part arrives)
  content = content.replace(/\[\[(?:\d+\]?\]?)?$/, "");

  // Escape a trailing unclosed `$$` so remark-math skips it mid-stream and
  // the user sees the LaTeX source streaming as plain text. The block swaps
  // to a rendered formula the moment the closing `$$` arrives.
  content = escapeIncompleteBlockMath(content);

  const codeBlockRegex = /```(\w*)\n[\s\S]*?```|```[\s\S]*?$/g;
  const matches = content.match(codeBlockRegex);

  if (matches) {
    content = matches.reduce((acc, match) => {
      if (!match.match(/```\w+/)) {
        return acc.replace(match, match.replace("```", "```plaintext"));
      }
      return acc;
    }, content);

    const lastMatch = matches[matches.length - 1];
    if (lastMatch && !lastMatch.endsWith("```")) {
      return escapeIncompleteInlineMath(preprocessLaTeX(content));
    }
  }

  const processed = preprocessLaTeX(content);
  return escapeIncompleteInlineMath(processed);
};

/**
 * Hook that provides markdown component callbacks for consistent rendering
 */
export const useMarkdownComponents = (
  state: FullChatState | undefined,
  processedContent: string,
  className?: string
) => {
  const paragraphCallback = useCallback(
    (props: any) => (
      <MemoizedParagraph className={className}>
        {props.children}
      </MemoizedParagraph>
    ),
    [className]
  );

  const anchorCallback = useCallback(
    (props: any) => {
      const imageFileId = extractChatImageFileId(
        props.href,
        String(props.children ?? "")
      );
      if (imageFileId) {
        return (
          <InMessageImage
            fileId={imageFileId}
            fileName={String(props.children ?? "")}
          />
        );
      }
      return (
        <MemoizedAnchor
          updatePresentingDocument={state?.setPresentingDocument || (() => {})}
          docs={state?.docs || []}
          userFiles={state?.userFiles || []}
          citations={state?.citations}
          href={props.href}
        >
          {props.children}
        </MemoizedAnchor>
      );
    },
    [
      state?.docs,
      state?.userFiles,
      state?.citations,
      state?.setPresentingDocument,
    ]
  );

  const markdownComponents = useMemo(
    () => ({
      a: anchorCallback,
      p: paragraphCallback,
      pre: ({ node, className, children }: any) => {
        // Don't render the pre wrapper - CodeBlock handles its own wrapper
        return <>{children}</>;
      },
      b: ({ node, className, children }: any) => {
        return <span className={className}>{children}</span>;
      },
      ul: ({ node, className, children, ...props }: any) => {
        return (
          <ul className={className} {...props}>
            {children}
          </ul>
        );
      },
      ol: ({ node, className, children, ...props }: any) => {
        return (
          <ol className={className} {...props}>
            {children}
          </ol>
        );
      },
      li: ({ node, className, children, ...props }: any) => {
        return (
          <li className={className} {...props}>
            {children}
          </li>
        );
      },
      table: ({ node, className, children, ...props }: any) => {
        return (
          <ScrollableTable className={className} {...props}>
            {children}
          </ScrollableTable>
        );
      },
      code: ({ node, className, children }: any) => {
        const codeText = extractCodeText(node, processedContent, children);

        return (
          <CodeBlock className={className} codeText={codeText}>
            {children}
          </CodeBlock>
        );
      },
    }),
    [anchorCallback, paragraphCallback, processedContent]
  );

  return markdownComponents;
};

/**
 * Renders markdown content with consistent configuration
 */
export const renderMarkdown = (
  content: string,
  markdownComponents: any,
  textSize: string = "text-base"
): JSX.Element => {
  return (
    <div dir="auto">
      <ReactMarkdown
        className={`prose dark:prose-invert font-main-content-body max-w-full ${textSize}`}
        components={markdownComponents}
        remarkPlugins={[
          remarkGfm,
          [remarkMath, { singleDollarTextMath: true }],
        ]}
        rehypePlugins={[rehypeHighlight, rehypeKatex]}
        urlTransform={transformLinkUri}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
};

/**
 * Complete markdown processing and rendering utility
 */
export const useMarkdownRenderer = (
  content: string,
  state: FullChatState | undefined,
  textSize: string
) => {
  const processedContent = useMemo(() => processContent(content), [content]);
  const markdownComponents = useMarkdownComponents(
    state,
    processedContent,
    textSize
  );

  const renderedContent = useMemo(
    () => renderMarkdown(processedContent, markdownComponents, textSize),
    [processedContent, markdownComponents, textSize]
  );

  return {
    processedContent,
    markdownComponents,
    renderedContent,
  };
};
