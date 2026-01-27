"use client";

import MinimalMarkdown from "@/components/chat/MinimalMarkdown";

/** Shared interface for the file renderer registry */
export interface FileRendererProps {
  content: string;
  fileName: string;
  filePath: string;
  mimeType: string;
  isImage: boolean;
}

export default function MarkdownFilePreview({ content }: FileRendererProps) {
  return (
    <div className="h-full flex flex-col">
      <div className="flex-1 overflow-auto p-6">
        <MinimalMarkdown
          content={content}
          className="max-w-3xl mx-auto"
          components={{
            a: ({ href, children }: any) => (
              <a
                href={href}
                target="_blank"
                rel="noopener noreferrer"
                className="text-link hover:text-link-hover underline"
              >
                {children}
              </a>
            ),
          }}
        />
      </div>
    </div>
  );
}
