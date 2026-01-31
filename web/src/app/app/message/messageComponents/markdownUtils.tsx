"use client";

import React, { useCallback, useMemo, JSX } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
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
import { extractCodeText, preprocessLaTeX } from "@/app/app/message/codeUtils";
import { CodeBlock } from "@/app/app/message/CodeBlock";
import { transformLinkUri, cn } from "@/lib/utils";

// react-markdown component props are complex generics; we use `any` for destructured
// props (matching the codebase pattern in MinimalMarkdown.tsx) while keeping return
// type annotations for overall type safety.
/* eslint-disable @typescript-eslint/no-explicit-any */

const noop = () => {};
const EMPTY_DOCS: NonNullable<FullChatState["docs"]> = [];
const EMPTY_USER_FILES: NonNullable<FullChatState["userFiles"]> = [];

/**
 * Adds `plaintext` to code fences without a language specifier.
 *
 * We do this before markdown rendering so syntax highlighting behaves consistently,
 * and so downstream components can assume ` ```<lang>` format.
 *
 * Implementation notes:
 * - We only rewrite **opening** fences; closing fences must remain ` ``` `.
 * - We use a simple state machine (toggle in/out of code fence) rather than
 *   regex+replace to avoid “replace first occurrence” pitfalls when identical
 *   matched substrings appear multiple times.
 * - Language identifiers may include `+`, `-`, `#`, `.` (e.g. `c++`, `c#`,
 *   `objective-c`, `.net`), so we treat whatever is between the opening fence and
 *   the newline as the info string.
 */
function addPlaintextToUnlabeledCodeFences(input: string): string {
  let out = "";
  let i = 0;
  let inFence = false;

  while (true) {
    const fenceIdx = input.indexOf("```", i);
    if (fenceIdx === -1) {
      out += input.slice(i);
      break;
    }

    out += input.slice(i, fenceIdx);

    if (inFence) {
      // Closing fence: never rewrite.
      out += "```";
      inFence = false;
      i = fenceIdx + 3;
      continue;
    }

    // Opening fence. Determine info string up to newline (or end if streaming).
    const infoStart = fenceIdx + 3;
    const newlineIdx = input.indexOf("\n", infoStart);

    // Streaming edge case: no newline yet (fence still being typed).
    if (newlineIdx === -1) {
      const info = input.slice(infoStart);
      if (info.length === 0) {
        out += "```plaintext";
      } else {
        out += input.slice(fenceIdx);
      }
      break;
    }

    const info = input.slice(infoStart, newlineIdx);
    if (info.trim().length === 0) {
      out += "```plaintext\n";
    } else {
      out += "```" + info + "\n";
    }

    inFence = true;
    i = newlineIdx + 1;
  }

  return out;
}

/**
 * Processes content for markdown rendering by handling code blocks and LaTeX.
 * Adds "plaintext" language to code blocks without a language specifier.
 */
export const processContent = (content: string): string => {
  content = addPlaintextToUnlabeledCodeFences(content);

  return preprocessLaTeX(content);
};

/**
 * Hook that provides markdown component callbacks for consistent rendering
 */
export const useMarkdownComponents = (
  state: FullChatState | undefined,
  processedContent: string,
  className?: string
): Components => {
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
        updatePresentingDocument={state?.setPresentingDocument ?? noop}
        docs={state?.docs ?? EMPTY_DOCS}
        userFiles={state?.userFiles ?? EMPTY_USER_FILES}
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
    (): Components => ({
      a: anchorCallback,
      p: paragraphCallback,
      pre: ({ children }: any) => {
        // Don't render the pre wrapper - CodeBlock handles its own wrapper
        return <>{children}</>;
      },
      b: ({ className, children }: any) => {
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
  markdownComponents: Components,
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
  const processedContent = useMemo(
    () => processContent(content),
    [content]
  );
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
