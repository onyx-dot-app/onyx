import { useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { cn } from "@opal/utils";

const ALLOWED_ELEMENTS = ["p", "a", "strong", "em", "code", "del"];

const INLINE_COMPONENTS = {
  p: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  a: ({ children, href }: { children?: React.ReactNode; href?: string }) => (
    <a
      href={href}
      className="underline underline-offset-2"
      target="_blank"
      rel="noopener noreferrer"
    >
      {children}
    </a>
  ),
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
  className?: string;
}

export default function InlineMarkdown({
  content,
  className,
}: InlineMarkdownProps) {
  const components = useMemo(() => INLINE_COMPONENTS, []);

  return (
    <ReactMarkdown
      className={className}
      components={components}
      allowedElements={ALLOWED_ELEMENTS}
      unwrapDisallowed
      remarkPlugins={[remarkGfm]}
    >
      {content}
    </ReactMarkdown>
  );
}
