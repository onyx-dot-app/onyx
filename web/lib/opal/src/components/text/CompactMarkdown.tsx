import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import Link from "next/link";
import type { Route } from "next";

import { cn } from "@opal/utils";

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
  "pre",
  "del",
  "blockquote",
  "ul",
  "ol",
  "li",
  "h1",
  "h2",
  "h3",
  "h4",
  "h5",
  "h6",
  "table",
  "thead",
  "tbody",
  "tr",
  "th",
  "td",
];

const DEFAULT_COMPONENTS = {
  h1: ({ node, ...props }) => (
    <p
      className="mt-3 first:mt-0 mb-1 text-sm font-semibold text-text-05"
      {...props}
    />
  ),
  h2: ({ node, ...props }) => (
    <p
      className="mt-3 first:mt-0 mb-1 text-sm font-semibold text-text-05"
      {...props}
    />
  ),
  h3: ({ node, ...props }) => (
    <p
      className="mt-2 first:mt-0 mb-1 text-sm font-semibold text-text-05"
      {...props}
    />
  ),
  h4: ({ node, ...props }) => (
    <p
      className="mt-2 first:mt-0 mb-1 text-sm font-medium text-text-05"
      {...props}
    />
  ),
  h5: ({ node, ...props }) => (
    <p
      className="mt-2 first:mt-0 mb-1 text-sm font-medium text-text-05"
      {...props}
    />
  ),
  h6: ({ node, ...props }) => (
    <p
      className="mt-2 first:mt-0 mb-1 text-sm font-medium text-text-05"
      {...props}
    />
  ),
  p: ({ node, ...props }) => (
    <p className="my-1 text-sm leading-6 text-text-04" {...props} />
  ),
  ul: ({ node, ...props }) => (
    <ul
      className="my-1 pl-5 list-disc text-sm leading-6 text-text-04"
      {...props}
    />
  ),
  ol: ({ node, ...props }) => (
    <ol
      className="my-1 pl-5 list-decimal text-sm leading-6 text-text-04"
      {...props}
    />
  ),
  li: ({ node, ...props }) => <li className="my-0.5 pl-1" {...props} />,
  strong: ({ node, ...props }) => (
    <strong className="font-semibold text-text-05" {...props} />
  ),
  em: ({ node, ...props }) => <em className="text-text-04" {...props} />,
  a: ({ children, href, node: _node, ...props }) => {
    if (!href) return <>{children}</>;
    const isRelative = href.startsWith("/") || href.startsWith("#");
    if (isRelative) {
      return (
        <Link
          href={href as Route}
          className="text-link hover:text-link-hover underline underline-offset-2"
          {...props}
        >
          {children}
        </Link>
      );
    }
    const isHttp = /^https?:/i.test(href);
    return (
      <a
        href={href}
        className="text-link hover:text-link-hover underline underline-offset-2"
        {...(isHttp ? { target: "_blank", rel: "noopener noreferrer" } : {})}
        {...props}
      >
        {children}
      </a>
    );
  },
  blockquote: ({ node, ...props }) => (
    <blockquote
      className="my-2 border-l border-border-02 pl-3 text-sm text-text-03"
      {...props}
    />
  ),
  pre: ({ node, ...props }) => (
    <pre
      className="my-2 overflow-x-hidden whitespace-pre-wrap wrap-break-word rounded-08 border border-border-01 bg-background-tint-01 p-2 text-xs leading-5 text-text-04"
      {...props}
    />
  ),
  code: ({ node, className, ...props }) => (
    <code
      className={cn(
        className,
        className
          ? "whitespace-pre-wrap wrap-break-word"
          : "rounded-04 bg-background-tint-02 px-1 py-0.5 text-xs text-text-05 wrap-break-word"
      )}
      {...props}
    />
  ),
  table: ({ node, ...props }) => (
    <div className="my-2 overflow-hidden rounded-08 border border-border-01">
      <table
        className="w-full table-fixed border-collapse text-left text-xs"
        {...props}
      />
    </div>
  ),
  th: ({ node, ...props }) => (
    <th
      className="border-b border-r border-border-01 bg-background-tint-01 px-2 py-1.5 align-top font-semibold text-text-05 wrap-break-word last:border-r-0"
      {...props}
    />
  ),
  td: ({ node, ...props }) => (
    <td
      className="border-b border-r border-border-01 px-2 py-1.5 align-top text-text-04 wrap-break-word last:border-r-0"
      {...props}
    />
  ),
} satisfies Components;

export interface CompactMarkdownProps {
  children: string;
  className?: string;
  components?: Partial<Components>;
}

export default function CompactMarkdown({
  children,
  className,
  components,
}: CompactMarkdownProps) {
  return (
    <ReactMarkdown
      className={cn(
        "max-w-full min-w-0 font-main-content-body wrap-break-word",
        className
      )}
      allowedElements={ALLOWED_ELEMENTS}
      unwrapDisallowed
      components={{ ...DEFAULT_COMPONENTS, ...components }}
      remarkPlugins={[remarkGfm]}
      rehypePlugins={[[rehypeSanitize, sanitizeSchema]]}
    >
      {children}
    </ReactMarkdown>
  );
}
