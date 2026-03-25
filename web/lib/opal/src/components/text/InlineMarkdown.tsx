import type { ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const SAFE_PROTOCOL = /^https?:|^mailto:|^tel:/i;

const ALLOWED_ELEMENTS = ["p", "a", "strong", "em", "code", "del"];

const INLINE_COMPONENTS = {
  p: ({ children }: { children?: ReactNode }) => <>{children}</>,
  a: ({ children, href }: { children?: ReactNode; href?: string }) => {
    if (!href || !SAFE_PROTOCOL.test(href)) {
      return <>{children}</>;
    }
    const isHttp = /^https?:/i.test(href);
    return (
      <a
        href={href}
        className="underline underline-offset-2"
        {...(isHttp ? { target: "_blank", rel: "noopener noreferrer" } : {})}
      >
        {children}
      </a>
    );
  },
  code: ({ children }: { children?: ReactNode }) => (
    <code className="font-main-ui-mono bg-background-tint-02 rounded px-1 py-0.5">
      {children}
    </code>
  ),
};

interface InlineMarkdownProps {
  content: string;
}

export default function InlineMarkdown({ content }: InlineMarkdownProps) {
  return (
    <ReactMarkdown
      components={INLINE_COMPONENTS}
      allowedElements={ALLOWED_ELEMENTS}
      unwrapDisallowed
      remarkPlugins={[remarkGfm]}
    >
      {content}
    </ReactMarkdown>
  );
}
