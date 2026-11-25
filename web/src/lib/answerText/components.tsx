"use client";

import { memo, useMemo } from "react";
import ReactMarkdown, {
  type Components,
  type ExtraProps,
} from "react-markdown";
import type { PluggableList } from "unified";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import { useTranslations } from "next-intl";
import { InputCheckbox } from "@opal/components";
import {
  SvgAlertCircle,
  SvgAlertTriangle,
  SvgChevronRight,
  SvgInfo,
  SvgLightbulbSimple,
  SvgXOctagon,
} from "@opal/icons";
import { Content, Section } from "@opal/layouts";
import type { IconFunctionComponent, StatusColor } from "@opal/types";
import { cn } from "@opal/utils";
import {
  MemoizedLink,
  MemoizedParagraph,
} from "@/lib/timeline/chat/message/MemoizedTextComponents";
import { ScrollableTable } from "@/lib/timeline/chat/message/messageComponents/markdownUtils";
import { tableToCopyContent } from "@/lib/timeline/chat/message/tableCopyUtils";
import { transformLinkUri } from "@/lib/utils";
import { rehypeDirection } from "@/lib/rehypeDirection";
import {
  RESPONSE_CURSOR_ANCHOR_ATTRIBUTE,
  rehypeStreamingCursor,
} from "@/lib/rehypeStreamingCursor";
import { useInResponse } from "@/lib/timeline/components/Response";
import { prepareAnswerMarkdown } from "@/lib/answerText/utils";
import {
  endsInOpenCodeFence,
  splitMarkdownBlocks,
} from "@/lib/answerText/streamBlocks";
import { ANSWER_REMARK_PLUGINS } from "@/lib/answerText/remarkPlugins";
import {
  AnswerCodeBlock,
  InlineCode,
  StreamingCodeContext,
  textOf,
} from "@/lib/answerText/codeBlocks";

const REHYPE_PLUGINS: PluggableList = [rehypeKatex, rehypeDirection];

const CALLOUTS = {
  note: { icon: SvgInfo, color: "info", border: "border-theme-blue-05" },
  tip: {
    icon: SvgLightbulbSimple,
    color: "success",
    border: "border-theme-green-05",
  },
  important: {
    icon: SvgAlertCircle,
    color: "queued",
    border: "border-theme-purple-05",
  },
  warning: {
    icon: SvgAlertTriangle,
    color: "warning",
    border: "border-status-warning-05",
  },
  caution: {
    icon: SvgXOctagon,
    color: "error",
    border: "border-status-error-05",
  },
} as const satisfies Record<
  string,
  { icon: IconFunctionComponent; color: StatusColor; border: string }
>;

type CalloutKind = keyof typeof CALLOUTS;

function isCalloutKind(value: unknown): value is CalloutKind {
  return typeof value === "string" && Object.hasOwn(CALLOUTS, value);
}

/** A blockquote, or a GitHub alert (`> [!NOTE]`) as a callout. */
function AnswerBlockquote({
  node,
  children,
  ...rest
}: React.ComponentProps<"blockquote"> & ExtraProps) {
  const t = useTranslations("chat.messages.callout");
  const kind = node?.properties.dataAlert;
  if (!isCalloutKind(kind)) {
    return <blockquote {...rest}>{children}</blockquote>;
  }
  const callout = CALLOUTS[kind];
  return (
    <div
      role="note"
      data-alert={kind}
      dir={rest.dir}
      className={cn(
        "my-4 border-s-2 ps-3 [&>:nth-child(2)]:mt-1 [&>:last-child]:mb-0",
        callout.border
      )}
    >
      <div className="not-prose" data-chat-find-ignore>
        <Content
          icon={callout.icon}
          title={t(`${kind}.title`)}
          color={callout.color}
          font="main-ui-action"
          width="fit"
        />
      </div>
      {children}
    </div>
  );
}

/** `<details>` from `remarkDetails`: a native disclosure. */
function AnswerDetails({
  node: _node,
  className,
  children,
  ...rest
}: React.ComponentProps<"details"> & ExtraProps) {
  return (
    <details
      {...rest}
      // Child combinators, so an open block never turns a nested block's chevron.
      className={cn(
        className,
        "my-4 [&>summary_svg]:transition-transform [&[open]>summary_svg]:rotate-90"
      )}
    >
      {children}
    </details>
  );
}

function AnswerSummary({ node }: React.ComponentProps<"summary"> & ExtraProps) {
  return (
    <summary className="not-prose list-none cursor-pointer [&::-webkit-details-marker]:hidden">
      <Content
        icon={SvgChevronRight}
        title={node ? textOf(node.children) : ""}
        font="main-ui-action"
        width="fit"
      />
    </summary>
  );
}

/**
 * The checkbox GFM puts first in a task item, or first in its paragraph
 * when the list is loose.
 */
function taskCheckbox(item: Element | undefined): Element | undefined {
  const first = item?.children.find(
    (child): child is Element => child.type === "element"
  );
  const box =
    first?.tagName === "p"
      ? first.children.find(
          (child): child is Element => child.type === "element"
        )
      : first;
  return box?.tagName === "input" ? box : undefined;
}

/**
 * A GFM task item: a read-only checkbox and no bullet. The checkbox sits
 * beside the item's content, not inside its paragraph, because the Opal
 * checkbox is a block element.
 */
function AnswerListItem({
  node,
  className,
  children,
  ...rest
}: React.ComponentProps<"li"> & ExtraProps) {
  const box = taskCheckbox(node);
  if (!box) {
    return (
      <li {...rest} className={className}>
        {children}
      </li>
    );
  }
  return (
    <li {...rest} className={cn(className, "list-none")}>
      <Section
        flexDirection="row"
        justifyContent="start"
        alignItems="start"
        gap={2}
        height="auto"
      >
        <div className="mt-1">
          <InputCheckbox checked={box.properties.checked === true} disabled />
        </div>
        <div className="min-w-0 grow [&>:first-child]:mt-0 [&>:last-child]:mb-0">
          {children}
        </div>
      </Section>
    </li>
  );
}

const BASE_COMPONENTS: Components = {
  a: MemoizedLink,
  blockquote: AnswerBlockquote,
  details: AnswerDetails,
  summary: AnswerSummary,
  li: AnswerListItem,
  // GFM's task box: `AnswerListItem` draws it.
  input: () => null,
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

interface AnswerMarkdownBlockProps {
  markdown: string;
  components: Components;
  rehypePlugins: PluggableList;
}

const AnswerMarkdownBlock = memo(function AnswerMarkdownBlock({
  markdown,
  components,
  rehypePlugins,
}: AnswerMarkdownBlockProps) {
  return (
    <ReactMarkdown
      components={components}
      remarkPlugins={ANSWER_REMARK_PLUGINS}
      rehypePlugins={rehypePlugins}
      urlTransform={transformLinkUri}
    >
      {markdown}
    </ReactMarkdown>
  );
});

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
 * Each block renders on its own, so while streaming only the last block
 * re-renders.
 */
export function AnswerMarkdown({
  content,
  streaming = false,
  cursor = false,
  components,
}: AnswerMarkdownProps) {
  const inResponse = useInResponse();
  const markdownComponents = useMemo<Components>(
    () => ({ ...BASE_COMPONENTS, ...components }),
    [components]
  );
  const markdown = useMemo(() => prepareAnswerMarkdown(content), [content]);
  // Split finished answers too: a block that changes parent on completion
  // remounts and loses its state, such as a code block's wrap choice.
  const blocks = useMemo(
    () => splitMarkdownBlocks(markdown) ?? [markdown],
    [markdown]
  );
  // The cursor would sit under an open code block, as code never holds it.
  const cursorHidden =
    cursor && endsInOpenCodeFence(blocks[blocks.length - 1] ?? "");
  const lastBlockRehypePlugins = useMemo<PluggableList>(
    () =>
      cursor && !cursorHidden
        ? [...REHYPE_PLUGINS, [rehypeStreamingCursor, { anchor: inResponse }]]
        : REHYPE_PLUGINS,
    [cursor, cursorHidden, inResponse]
  );

  return (
    <StreamingCodeContext.Provider value={streaming}>
      {/* dir="auto" backstops renderers that do not forward the per-block
          dir stamped by rehypeDirection. */}
      <div
        dir="auto"
        className={cn(
          "response-text prose prose-onyx font-main-content-body max-w-full wrap-break-word",
          streaming && "streaming-katex"
        )}
      >
        {blocks.map((block, index) => (
          <AnswerMarkdownBlock
            key={index}
            markdown={block}
            components={markdownComponents}
            rehypePlugins={
              index === blocks.length - 1
                ? lastBlockRehypePlugins
                : REHYPE_PLUGINS
            }
          />
        ))}
        {/* The response's cursor fades out here instead of holding its
            place above the code. */}
        {cursorHidden && inResponse && (
          <span hidden {...{ [RESPONSE_CURSOR_ANCHOR_ATTRIBUTE]: "hidden" }} />
        )}
      </div>
    </StreamingCodeContext.Provider>
  );
}

export default AnswerMarkdown;
