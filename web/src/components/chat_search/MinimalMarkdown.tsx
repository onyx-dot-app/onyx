import { CodeBlock } from "@/app/chat/message/CodeBlock";
import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface MinimalMarkdownProps {
  content: string;
  className?: string;
  useCodeBlock?: boolean;
}

export const MinimalMarkdown: React.FC<MinimalMarkdownProps> = ({
  content,
  className = "",
  useCodeBlock = false,
}) => {
  return (
    <ReactMarkdown
      className={`w-full text-wrap break-word ${className}`}
      components={{
        a: ({ node, ...props }) => (
          <a
            {...props}
            className="text-sm text-link hover:text-link-hover"
            target="_blank"
            rel="noopener noreferrer"
          />
        ),
        p: ({ node, ...props }) => (
          <p {...props} className="text-wrap break-word text-sm m-0 w-full" />
        ),
        code: useCodeBlock
          ? (props) => (
              <CodeBlock className="w-full" {...props} content={content} />
            )
          : (props) => <code {...props} />,
      }}
      remarkPlugins={[remarkGfm]}
    >
      {content}
    </ReactMarkdown>
  );
};
