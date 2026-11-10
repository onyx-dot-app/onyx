"use client";

import type { ReactNode } from "react";
import MinimalMarkdown from "@/components/chat/MinimalMarkdown";

// MinimalMarkdown's default `p` goes through MemoizedParagraph which forces
// the Opal `mainContentBody` preset (~16px). Override every text-bearing
// element here so reasoning renders at a uniform smaller size.
interface ThinkingBlockProps {
  children?: ReactNode;
  dir?: string;
}

const thinkingP = ({ children, dir }: ThinkingBlockProps) => (
  <p dir={dir} className="text-sm leading-relaxed text-text-03 my-1">
    {children}
  </p>
);
const thinkingHeader = ({ children, dir }: ThinkingBlockProps) => (
  <p
    dir={dir}
    className="text-sm leading-relaxed text-text-03 font-semibold mt-4 mb-2"
  >
    {children}
  </p>
);

// LLM reasoning typically uses single \n between lines; markdown collapses
// those into whitespace by default. Promote single newlines to paragraph
// breaks so each line keeps its own visible break. Also break around bold
// spans that abut other content — LLMs frequently emit section headers as
// "...prevContent.**Header**NextContent..." without separators, and
// markdown otherwise renders that as inline bold mid-paragraph.
function normalizeThinking(text: string): string {
  let out = text.replace(/(?<!\n)\n(?!\n)/g, "\n\n");
  out = out.replace(/([.!?)\]])(\*\*[^*\n]+\*\*)/g, "$1\n\n$2");
  out = out.replace(/(\*\*[^*\n]+\*\*)(?=[A-Z([])/g, "$1\n\n");
  return out;
}
const thinkingLi = ({ children, dir }: ThinkingBlockProps) => (
  <li dir={dir} className="text-sm leading-relaxed text-text-03 my-0.5">
    {children}
  </li>
);
const thinkingUl = ({ children, dir }: ThinkingBlockProps) => (
  <ul dir={dir} className="list-disc ms-4 my-1 text-sm">
    {children}
  </ul>
);
const thinkingOl = ({ children, dir }: ThinkingBlockProps) => (
  <ol dir={dir} className="list-decimal ms-4 my-1 text-sm">
    {children}
  </ol>
);
const thinkingBlockquote = ({ children, dir }: ThinkingBlockProps) => (
  <blockquote
    dir={dir}
    className="text-sm text-text-02 border-s-2 border-border-02 ps-2 my-1"
  >
    {children}
  </blockquote>
);

const THINKING_MARKDOWN_OVERRIDES = {
  p: thinkingP,
  h1: thinkingHeader,
  h2: thinkingHeader,
  h3: thinkingHeader,
  h4: thinkingHeader,
  h5: thinkingHeader,
  h6: thinkingHeader,
  li: thinkingLi,
  ul: thinkingUl,
  ol: thinkingOl,
  blockquote: thinkingBlockquote,
};

interface ThinkingMarkdownProps {
  content: string;
  isStreaming: boolean;
}

/** The agent's reasoning text, as the body of a timeline thinking step. */
export default function ThinkingMarkdown({
  content,
  isStreaming,
}: ThinkingMarkdownProps) {
  return (
    <div className="py-1 max-h-48 overflow-y-auto">
      <MinimalMarkdown
        content={normalizeThinking(content)}
        className="text-text-03 prose-sm"
        streaming={isStreaming}
        components={THINKING_MARKDOWN_OVERRIDES}
      />
    </div>
  );
}
