import React, { useCallback, useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypePrism from "rehype-prism-plus";
import rehypeKatex from "rehype-katex";
import "prismjs/themes/prism-tomorrow.css";
import "katex/dist/katex.min.css";
import "../custom-code-styles.css";

import { FullChatState } from "./interfaces";
import { MemoizedAnchor, MemoizedParagraph } from "../MemoizedTextComponents";
import { extractCodeText, preprocessLaTeX } from "../codeUtils";
import { CodeBlock } from "../CodeBlock";
import { transformLinkUri } from "@/lib/utils";

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
  processedContent: string
) => {
  const paragraphCallback = useCallback(
    (props: any) => <MemoizedParagraph>{props.children}</MemoizedParagraph>,
    []
  );

  const anchorCallback = useCallback(
    (props: any) => (
      <MemoizedAnchor
        updatePresentingDocument={state?.setPresentingDocument || (() => {})}
        docs={state?.docs || []}
        userFiles={state?.userFiles || []}
        href={props.href}
      >
        {props.children}
      </MemoizedAnchor>
    ),
    [state?.docs, state?.userFiles, state?.setPresentingDocument]
  );

  const markdownComponents = useMemo(
    () => ({
      a: anchorCallback,
      p: paragraphCallback,
      b: ({ node, className, children }: any) => {
        return <span className={className}>{children}</span>;
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
    <ReactMarkdown
      className={`prose dark:prose-invert max-w-full ${textSize}`}
      components={markdownComponents}
      remarkPlugins={[remarkGfm, remarkMath]}
      rehypePlugins={[[rehypePrism, { ignoreMissing: true }], rehypeKatex]}
      urlTransform={transformLinkUri}
    >
      {content}
    </ReactMarkdown>
  );
};

/**
 * Complete markdown processing and rendering utility
 */
export const useMarkdownRenderer = (
  content: string,
  state: FullChatState | undefined,
  textSize: string = "text-base"
) => {
  const processedContent = useMemo(() => processContent(content), [content]);
  const markdownComponents = useMarkdownComponents(state, processedContent);

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
