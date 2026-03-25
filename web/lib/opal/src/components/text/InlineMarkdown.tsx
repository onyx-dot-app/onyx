import type { ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import type { RichStr } from "@opal/types";

// ---------------------------------------------------------------------------
// InlineMarkdown
// ---------------------------------------------------------------------------

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
    <code className="[font-family:var(--font-dm-mono)] bg-background-tint-02 rounded px-1 py-0.5">
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

// ---------------------------------------------------------------------------
// RichStr helpers
// ---------------------------------------------------------------------------

function isRichStr(value: unknown): value is RichStr {
  return (
    typeof value === "object" &&
    value !== null &&
    (value as RichStr).__brand === "RichStr"
  );
}

/** Resolves `string | RichStr` to a `ReactNode`. */
export function resolveStr(value: string | RichStr): ReactNode {
  return isRichStr(value) ? <InlineMarkdown content={value.raw} /> : value;
}

/** Extracts the plain string from `string | RichStr`. */
export function toPlainString(value: string | RichStr): string {
  return isRichStr(value) ? value.raw : value;
}

/** Resolves a `ReactNode` that may contain a `RichStr`. */
export function resolveChildren(children: ReactNode): ReactNode {
  return isRichStr(children) ? (
    <InlineMarkdown content={children.raw} />
  ) : (
    children
  );
}
