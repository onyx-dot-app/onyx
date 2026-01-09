import React, { useCallback, useMemo, JSX } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeHighlight from "rehype-highlight";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import "@/app/chat/message/custom-code-styles.css";
import { FullChatState } from "@/app/chat/message/messageComponents/interfaces";
import {
  MemoizedAnchor,
  MemoizedParagraph,
} from "@/app/chat/message/MemoizedTextComponents";
import { extractCodeText, preprocessLaTeX } from "@/app/chat/message/codeUtils";
import { CodeBlock } from "@/app/chat/message/CodeBlock";
import { transformLinkUri, cn } from "@/lib/utils";

/**
 * Processes content for markdown rendering by handling code blocks and LaTeX
 */
export const processContent = (content: string): string => {
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
      return preprocessLaTeX(content);
    }
  }

  const processed = preprocessLaTeX(content);
  return processed;
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
    (props: any) => (
      <MemoizedAnchor
        updatePresentingDocument={state?.setPresentingDocument || (() => {})}
        docs={state?.docs || []}
        userFiles={state?.userFiles || []}
        citations={state?.citations}
        href={props.href}
      >
        {props.children}
      </MemoizedAnchor>
    ),
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
          <div className="markdown-table-breakout">
            <table className={cn(className, "min-w-full")} {...props}>
              {children}
            </table>
          </div>
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
