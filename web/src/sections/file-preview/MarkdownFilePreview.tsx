"use client";

import { useMemo } from "react";
import ReactMarkdown from "react-markdown";
import type { PluggableList } from "unified";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeHighlight from "rehype-highlight";
import rehypeKatex from "rehype-katex";
import { useHighlightLanguages } from "@/hooks/useHighlightLanguages";
import { rehypeDirection } from "@/lib/rehypeDirection";
import { transformLinkUri } from "@/lib/utils";
import "katex/dist/katex.min.css";
import "@/app/app/message/custom-code-styles.css";

interface MarkdownFilePreviewProps {
  text: string;
}

/**
 * Markdown as a document, with its fenced code highlighted once grammars
 * load. Raw HTML in the source shows as text, and links pass
 * `transformLinkUri` and open in a new tab.
 */
export function MarkdownFilePreview({ text }: MarkdownFilePreviewProps) {
  const languages = useHighlightLanguages();
  const rehypePlugins = useMemo<PluggableList>(
    () =>
      languages
        ? [[rehypeHighlight, { languages }], rehypeKatex, rehypeDirection]
        : [rehypeKatex, rehypeDirection],
    [languages]
  );
  return (
    <div className="h-full overflow-auto p-6 pb-16">
      <ReactMarkdown
        className="prose prose-onyx max-w-none text-sm wrap-break-word"
        remarkPlugins={[
          remarkGfm,
          [remarkMath, { singleDollarTextMath: false }],
        ]}
        rehypePlugins={rehypePlugins}
        urlTransform={transformLinkUri}
        components={{
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noopener noreferrer">
              {children}
            </a>
          ),
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}
