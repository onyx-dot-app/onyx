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
import { transformLinkUri, URI_SCHEME_REGEX } from "@/lib/utils";
import "katex/dist/katex.min.css";
import "@/app/app/message/custom-code-styles.css";

interface MarkdownFilePreviewProps {
  text: string;
  // A file tile's preview: the document alone, without its images or a
  // scrolling frame
  thumbnail?: boolean;
}

/**
 * Markdown as a document, with its fenced code highlighted once grammars
 * load; a fence without a language stays plain, as in chat messages. Raw
 * HTML in the source shows as text. Links pass `transformLinkUri` and open in
 * a new tab: a link with a scheme stays as it is, and one that starts with
 * `www.` goes to its site. Any other link, such as a path relative to the
 * file, has no target outside the file, so it shows as plain text.
 */
export function MarkdownFilePreview({
  text,
  thumbnail = false,
}: MarkdownFilePreviewProps) {
  const languages = useHighlightLanguages();
  const rehypePlugins = useMemo<PluggableList>(
    () =>
      languages
        ? [[rehypeHighlight, { languages }], rehypeKatex, rehypeDirection]
        : [rehypeKatex, rehypeDirection],
    [languages]
  );
  const document = (
    <ReactMarkdown
      className="prose prose-onyx max-w-none text-sm wrap-break-word"
      remarkPlugins={[remarkGfm, [remarkMath, { singleDollarTextMath: false }]]}
      rehypePlugins={rehypePlugins}
      urlTransform={transformLinkUri}
      components={{
        ...(thumbnail && { img: () => null }),
        a: ({ href, children }) => {
          const target = href?.trim();
          const url = !target
            ? null
            : URI_SCHEME_REGEX.test(target)
              ? target
              : target.startsWith("www.")
                ? `https://${target}`
                : null;
          if (url === null) return <>{children}</>;
          return (
            <a href={url} target="_blank" rel="noopener noreferrer">
              {children}
            </a>
          );
        },
      }}
    >
      {text}
    </ReactMarkdown>
  );
  if (thumbnail) return document;
  return <div className="h-full overflow-auto p-6 pb-16">{document}</div>;
}
