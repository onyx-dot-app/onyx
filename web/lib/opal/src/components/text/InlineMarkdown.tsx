import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { cn } from "@opal/utils";

const SAFE_PROTOCOL = /^https?:|^mailto:|^tel:/i;

const ALLOWED_ELEMENTS = ["p", "a", "strong", "em", "code", "del"];

const INLINE_COMPONENTS = {
  p: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  a: ({ children, href }: { children?: React.ReactNode; href?: string }) => {
    const safeSrc = href && SAFE_PROTOCOL.test(href) ? href : undefined;
    return (
      <a
        href={safeSrc}
        className="underline underline-offset-2"
        target="_blank"
        rel="noopener noreferrer"
      >
        {children}
      </a>
    );
  },
  code: ({ children }: { children?: React.ReactNode }) => (
    <code
      className={cn(
        "font-main-ui-mono",
        "bg-background-tint-02 rounded px-1 py-0.5"
      )}
    >
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
