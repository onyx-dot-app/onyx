"use client";

import { createContext, useContext, useMemo } from "react";
import ReactMarkdown, {
  type Components,
  type ExtraProps,
} from "react-markdown";
import type { Element, ElementContent } from "hast";
import type { PluggableList } from "unified";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import { cn } from "@opal/utils";
import {
  MemoizedLink,
  MemoizedParagraph,
} from "@/app/app/message/MemoizedTextComponents";
import { ScrollableTable } from "@/app/app/message/messageComponents/markdownUtils";
import { tableToCopyContent } from "@/app/app/message/tableCopyUtils";
import { transformLinkUri } from "@/lib/utils";
import { rehypeDirection } from "@/lib/rehypeDirection";
import { rehypeStreamingCursor } from "@/lib/rehypeStreamingCursor";
import { useInResponse } from "@/lib/timeline/components/Response";
import { CodeBlockBody } from "@/lib/timeline/components/bodies/CodeBlockBody";
import { prepareAnswerMarkdown } from "@/lib/answerText/utils";

// Math is `$$…$$` only (see `prepareAnswerMarkdown`).
const REMARK_PLUGINS: PluggableList = [
  remarkGfm,
  [remarkMath, { singleDollarTextMath: false }],
];
const REHYPE_PLUGINS: PluggableList = [rehypeKatex, rehypeDirection];

const StreamingContext = createContext(false);

function textOf(nodes: ElementContent[]): string {
  return nodes
    .map((node) =>
      node.type === "text"
        ? node.value
        : node.type === "element"
          ? textOf(node.children)
          : ""
    )
    .join("");
}

/** A fenced code block: the `pre` around one `code`. */
function AnswerCodeBlock({ node }: React.ComponentProps<"pre"> & ExtraProps) {
  const streaming = useContext(StreamingContext);
  const code = node?.children.find(
    (child): child is Element =>
      child.type === "element" && child.tagName === "code"
  );
  const className = code?.properties.className;
  const languageClass = Array.isArray(className)
    ? className.find(
        (name): name is string =>
          typeof name === "string" && name.startsWith("language-")
      )
    : undefined;
  return (
    <CodeBlockBody
      code={code ? textOf(code.children).replace(/\n$/, "") : ""}
      language={languageClass?.slice("language-".length)}
      streaming={streaming}
    />
  );
}

/** Inline code. Fenced blocks never reach it: `pre` renders them whole. */
function InlineCode({ children }: React.ComponentProps<"code"> & ExtraProps) {
  return (
    // dir="ltr": code is always LTR, even inside RTL prose. The dir attribute
    // also bidi-isolates the run from the surrounding text.
    <span
      dir="ltr"
      data-testid="code-block"
      className="font-mono text-text-05 bg-background-tint-00 rounded-sm text-[0.75em] inline whitespace-pre-wrap wrap-break-word py-0.5 px-1"
    >
      {children}
    </span>
  );
}

const BASE_COMPONENTS: Components = {
  a: MemoizedLink,
  p: ({ dir, children }) => (
    <MemoizedParagraph dir={dir}>{children}</MemoizedParagraph>
  ),
  pre: AnswerCodeBlock,
  code: InlineCode,
  table: ({ node, className, children, ...rest }) => (
    <ScrollableTable
      className={className}
      getCopyContent={
        node ? () => tableToCopyContent(node, () => null) : undefined
      }
      {...rest}
    >
      {children}
    </ScrollableTable>
  ),
};

interface AnswerMarkdownProps {
  content: string;
  /** The text still grows: code highlights line by line and math fades in. */
  streaming?: boolean;
  /** Show the streaming cursor after the last character. */
  cursor?: boolean;
  /**
   * The app's own renderers, such as chat's citation links or Craft's output
   * file links. They replace the shared ones of the same tag.
   */
  components?: Components;
}

/**
 * Answer text, the same in chat and Craft: one markdown pipeline (GFM, `$$`
 * math, per-block direction), one look (`prose prose-onyx` on the main
 * content font), code blocks as `CodeBlockBody`, and the streaming cursor.
 */
export function AnswerMarkdown({
  content,
  streaming = false,
  cursor = false,
  components,
}: AnswerMarkdownProps) {
  const inResponse = useInResponse();
  const rehypePlugins = useMemo<PluggableList>(
    () =>
      cursor
        ? [...REHYPE_PLUGINS, [rehypeStreamingCursor, { anchor: inResponse }]]
        : REHYPE_PLUGINS,
    [cursor, inResponse]
  );
  const markdownComponents = useMemo<Components>(
    () => ({ ...BASE_COMPONENTS, ...components }),
    [components]
  );
  const markdown = useMemo(() => prepareAnswerMarkdown(content), [content]);

  return (
    <StreamingContext.Provider value={streaming}>
      {/* dir="auto" backstops renderers that do not forward the per-block
          dir stamped by rehypeDirection. */}
      <div dir="auto" className={cn(streaming && "streaming-katex")}>
        <ReactMarkdown
          className="response-text prose prose-onyx font-main-content-body max-w-full wrap-break-word"
          components={markdownComponents}
          remarkPlugins={REMARK_PLUGINS}
          rehypePlugins={rehypePlugins}
          urlTransform={transformLinkUri}
        >
          {markdown}
        </ReactMarkdown>
      </div>
    </StreamingContext.Provider>
  );
}

export default AnswerMarkdown;
