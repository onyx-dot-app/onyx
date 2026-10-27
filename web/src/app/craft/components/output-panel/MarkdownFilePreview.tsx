"use client";

import { memo } from "react";
import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { rehypeDirection } from "@/lib/rehypeDirection";
import {
  FilePreviewScrollArea,
  type FilePreviewScrollPosition,
} from "@/app/craft/components/output-panel/FilePreviewScrollArea";
import remarkGfm from "remark-gfm";
import { transformLinkUri } from "@/lib/utils";

interface MarkdownFilePreviewProps extends FilePreviewScrollPosition {
  content: string;
}

export default function MarkdownFilePreview({
  content,
  initialScrollTop,
  onScrollTopChange,
  isActive,
}: MarkdownFilePreviewProps) {
  return (
    <FilePreviewScrollArea
      initialScrollTop={initialScrollTop}
      onScrollTopChange={onScrollTopChange}
      isActive={isActive}
      padding={6}
    >
      <MarkdownContent content={content} />
    </FilePreviewScrollArea>
  );
}

function MarkdownContentView({
  content,
  thumbnail = false,
}: {
  content: string;
  thumbnail?: boolean;
}) {
  return (
    <ReactMarkdown
      className="prose max-w-none text-sm wrap-break-word"
      remarkPlugins={[remarkGfm, [remarkMath, { singleDollarTextMath: false }]]}
      rehypePlugins={[rehypeKatex, rehypeDirection]}
      urlTransform={transformLinkUri}
      components={{
        ...(thumbnail && { img: () => null }),
        a: ({ href, children }) => (
          <a href={href} target="_blank" rel="noopener noreferrer">
            {children}
          </a>
        ),
      }}
    >
      {content}
    </ReactMarkdown>
  );
}

export const MarkdownContent = memo(MarkdownContentView);
