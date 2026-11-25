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
import { Content } from "@opal/layouts";
import type {
  IconFunctionComponent,
  IconProps,
  StatusColor,
} from "@opal/types";
import { cn } from "@opal/utils";
import {
  MemoizedLink,
  MemoizedParagraph,
} from "@/lib/timeline/chat/message/MemoizedTextComponents";
import { ScrollableTable } from "@/lib/timeline/chat/message/messageComponents/markdownUtils";
import { tableToCopyContent } from "@/lib/timeline/chat/message/tableCopyUtils";
import { transformLinkUri } from "@/lib/utils";
import { rehypeDirection } from "@/lib/rehypeDirection";
import { rehypeStreamingCursor } from "@/lib/rehypeStreamingCursor";
import { useInResponse } from "@/lib/timeline/components/Response";
import { prepareAnswerMarkdown } from "@/lib/answerText/utils";
import { splitMarkdownBlocks } from "@/lib/answerText/streamBlocks";
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

function DetailsChevron({ className, ...props }: IconProps) {
  return (
    <SvgChevronRight
      {...props}
      className={cn(className, "transition-transform group-open:rotate-90")}
    />
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
    <details {...rest} className={cn(className, "group my-4")}>
      {children}
    </details>
  );
}

function AnswerSummary({ node }: React.ComponentProps<"summary"> & ExtraProps) {
  return (
    <summary className="not-prose list-none cursor-pointer [&::-webkit-details-marker]:hidden">
      <Content
        icon={DetailsChevron}
        title={node ? textOf(node.children) : ""}
        font="main-ui-action"
        width="fit"
      />
    </summary>
  );
}

/** A GFM task list item: no bullet; its checkbox is `TaskCheckbox`. */
function AnswerListItem({
  node: _node,
  className,
  children,
  ...rest
}: React.ComponentProps<"li"> & ExtraProps) {
  return (
    <li
      {...rest}
      className={cn(
        className,
        className?.includes("task-list-item") && "list-none"
      )}
    >
      {children}
    </li>
  );
}

/** GFM renders a task's box as a disabled input; show it read-only. */
function TaskCheckbox({
  type,
  checked,
}: React.ComponentProps<"input"> & ExtraProps) {
  if (type !== "checkbox") return null;
  return (
    <span className="-ms-6 me-2 inline-block align-middle">
      <InputCheckbox checked={checked === true} disabled />
    </span>
  );
}

const BASE_COMPONENTS: Components = {
  a: MemoizedLink,
  blockquote: AnswerBlockquote,
  details: AnswerDetails,
  summary: AnswerSummary,
  li: AnswerListItem,
  input: TaskCheckbox,
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
 * While streaming, finished blocks keep their render and only the last block
 * re-renders.
 */
export function AnswerMarkdown({
  content,
  streaming = false,
  cursor = false,
  components,
}: AnswerMarkdownProps) {
  const inResponse = useInResponse();
  const lastBlockRehypePlugins = useMemo<PluggableList>(
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
  const blocks = (streaming ? splitMarkdownBlocks(markdown) : null) ?? [
    markdown,
  ];

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
      </div>
    </StreamingCodeContext.Provider>
  );
}

export default AnswerMarkdown;
