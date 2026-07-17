import type { ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import Link from "next/link";
import type { Route } from "next";

import type { RichStr } from "@opal/types";

// ---------------------------------------------------------------------------
// InlineMarkdown
// ---------------------------------------------------------------------------

const sanitizeSchema = {
  ...defaultSchema,
  protocols: {
    ...defaultSchema.protocols,
    href: [...(defaultSchema.protocols?.href ?? []), "tel"],
  },
};

const ALLOWED_ELEMENTS = [
  "p",
  "br",
  "a",
  "strong",
  "em",
  "code",
  "del",
  "ul",
  "ol",
  "li",
];

const INLINE_COMPONENTS = {
  p: ({ children }: { children?: ReactNode }) => (
    <span className="block">{children}</span>
  ),
  ul: ({ children }: { children?: ReactNode }) => (
    <ul className="list-disc pl-3 space-y-0">{children}</ul>
  ),
  ol: ({ children }: { children?: ReactNode }) => (
    <ol className="list-decimal pl-3">{children}</ol>
  ),
  li: ({ children }: { children?: ReactNode }) => <li>{children}</li>,
  a: ({ children, href }: { children?: ReactNode; href?: string }) => {
    if (!href) return <>{children}</>;
    // rehype-sanitize has already stripped unsafe hrefs — routing decision only.
    const isRelative = href.startsWith("/") || href.startsWith("#");
    if (isRelative) {
      return (
        <Link href={href as Route} className="underline underline-offset-2">
          {children}
        </Link>
      );
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
    <code className="[font-family:var(--font-dm-mono)] bg-background-tint-02 rounded-sm px-1 py-0.5">
      {children}
    </code>
  ),
};

interface InlineMarkdownProps {
  content: string;
}

export default function InlineMarkdown({ content }: InlineMarkdownProps) {
  // Convert \n to CommonMark hard line breaks (two trailing spaces + newline).
  // react-markdown renders these as <br />, which inherits the parent's
  // line-height for font-appropriate spacing.
  const normalized = content.replace(/\n/g, "  \n");

  return (
    <ReactMarkdown
      components={INLINE_COMPONENTS}
      allowedElements={ALLOWED_ELEMENTS}
      unwrapDisallowed
      remarkPlugins={[remarkGfm]}
      rehypePlugins={[[rehypeSanitize, sanitizeSchema]]}
    >
      {normalized}
    </ReactMarkdown>
  );
}

// ---------------------------------------------------------------------------
// RichStr helpers
// ---------------------------------------------------------------------------

export function isRichStr(value: unknown): value is RichStr {
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

/** Extracts the plain string from `string | RichStr`, stripping markdown syntax. */
export function toPlainString(value: string | RichStr): string {
  if (!isRichStr(value)) return value;
  return value.raw
    .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/(?<!\w)__([^_]+)__(?!\w)/g, "$1")
    .replace(/~~([^~]+)~~/g, "$1")
    .replace(/\*([^*]+)\*/g, "$1")
    .replace(/(?<!\w)_([^_]+)_(?!\w)/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\s*\n\s*/g, " ")
    .trim();
}
