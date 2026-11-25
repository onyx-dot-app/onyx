import React, {
  createContext,
  useContext,
  useCallback,
  useEffect,
  useRef,
  useMemo,
  useState,
  JSX,
} from "react";
import ReactMarkdown, {
  type Components,
  type ExtraProps,
} from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeHighlight from "rehype-highlight";
import type { LanguageFn } from "highlight.js";
import { useHighlightLanguages } from "@/hooks/useHighlightLanguages";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import "@/lib/timeline/chat/message/custom-code-styles.css";
import { FullChatState } from "@/lib/timeline/chat/message/messageComponents/types";
import {
  MemoizedAnchor,
  MemoizedParagraph,
} from "@/lib/timeline/chat/message/MemoizedTextComponents";
import {
  extractCodeText,
  preprocessLaTeX,
  escapeIncompleteBlockMath,
  escapeIncompleteInlineMath,
  labelBareCodeFences,
} from "@/lib/timeline/chat/message/codeUtils";
import { CodeBlock } from "@/lib/timeline/chat/message/CodeBlock";
import { transformLinkUri } from "@/lib/utils";
import { rehypeDirection } from "@/lib/rehypeDirection";
import { cn, clickOnKeyDown } from "@opal/utils";
import { Text } from "@opal/components";
import type { TextColor, TextFont } from "@opal/components";
import { InMessageImage } from "@/app/app/components/files/images/InMessageImage";
import { FullImageModal } from "@/app/app/components/files/images/FullImageModal";
import { extractChatImageFileId } from "@/app/app/components/files/images/utils";
import { CopyButton } from "@opal/components";
import { Hoverable } from "@opal/core";
import { useTranslations } from "next-intl";
import {
  TableCopyContent,
  createCitationResolver,
  tableToCopyContent,
} from "@/lib/timeline/chat/message/tableCopyUtils";

/** Table wrapper that detects horizontal overflow and shows a fade + scrollbar. */
interface ScrollableTableProps extends React.TableHTMLAttributes<HTMLTableElement> {
  children: React.ReactNode;
  /** When set, shows a hover/focus copy button for this table. */
  getCopyContent?: () => TableCopyContent;
}

export function ScrollableTable({
  className,
  children,
  dir,
  getCopyContent,
  ...props
}: ScrollableTableProps) {
  const t = useTranslations("chat.messages");
  const scrollRef = useRef<HTMLDivElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const tableRef = useRef<HTMLTableElement>(null);

  useEffect(() => {
    const el = scrollRef.current;
    const wrap = wrapRef.current;
    const table = tableRef.current;
    if (!el || !wrap) return;

    const check = () => {
      const overflows = el.scrollWidth > el.clientWidth;
      // Logical distance from the scroll start. RTL scrollLeft runs from
      // 0 down to negative, and the CSS paints on inline edges to match.
      const maxScroll = el.scrollWidth - el.clientWidth;
      const fromStart =
        getComputedStyle(el).direction === "rtl"
          ? -el.scrollLeft
          : el.scrollLeft;
      const atEnd = fromStart >= maxScroll - 2;
      wrap.dataset.overflows = overflows && !atEnd ? "true" : "false";
    };

    check();
    el.addEventListener("scroll", check, { passive: true });
    // Observe both the scroll container (parent resize) and the table
    // itself (content growth during streaming).
    const ro = new ResizeObserver(check);
    ro.observe(el);
    if (table) ro.observe(table);

    return () => {
      el.removeEventListener("scroll", check);
      ro.disconnect();
    };
  }, []);

  return (
    // The stamped table dir lifts onto the scroller so scrollLeft semantics
    // and the initial scroll edge follow the table's own direction.
    <div ref={wrapRef} dir={dir} className="markdown-table-card">
      <Hoverable.Root group="markdownTable">
        <div ref={scrollRef} className="markdown-table-breakout">
          <table ref={tableRef} className={cn(className, "my-0!")} {...props}>
            {children}
          </table>
        </div>
        {getCopyContent && (
          <div className="markdown-table-copy">
            <Hoverable.Item group="markdownTable" variant="appear-on-hover">
              <div className="markdown-table-copy-surface">
                <CopyButton
                  size="sm"
                  getCopyText={() => getCopyContent().tsv}
                  getHtmlContent={() => getCopyContent().html}
                  tooltip={t("markdownTable.copyButton.label")}
                  aria-label={t("markdownTable.copyButton.label")}
                  data-testid="markdown-table-copy-button"
                />
              </div>
            </Hoverable.Item>
          </div>
        )}
      </Hoverable.Root>
    </div>
  );
}

/**
 * Processes content for markdown rendering by handling code blocks and LaTeX
 */
/**
 * Strips a citation link still arriving at the end of streaming content.
 * During typewriter animation, [[N]](url) is revealed character by character,
 * and ReactMarkdown can't parse an incomplete link: it would show as raw text.
 */
const LinkedMarkdownImage = createContext(false);

export function MarkdownLinkContent({ children }: React.PropsWithChildren) {
  return (
    <LinkedMarkdownImage.Provider value>
      {children}
    </LinkedMarkdownImage.Provider>
  );
}

type MarkdownImageProps = React.ComponentProps<"img"> & ExtraProps;

export function MarkdownImage(props: MarkdownImageProps) {
  return <MarkdownImageContent key={String(props.src ?? "")} {...props} />;
}

function MarkdownImageContent({ src, alt, title }: MarkdownImageProps) {
  const linked = useContext(LinkedMarkdownImage);
  const t = useTranslations("chat.messages");
  const tFiles = useTranslations("chat.files");
  const triggerRef = useRef<HTMLSpanElement>(null);
  const [failed, setFailed] = useState(false);
  const [fullImageShowing, setFullImageShowing] = useState(false);

  if (typeof src !== "string" || src === "" || failed) {
    return (
      <span className="inline-block rounded-lg border border-01 px-2 py-1">
        <Text font="secondary-body" color="text-03">
          {alt
            ? t("markdownImage.unavailable.withAlt", { alt })
            : t("markdownImage.unavailable.text")}
        </Text>
      </span>
    );
  }

  const image = (
    <img
      src={src}
      alt={alt ?? ""}
      title={title}
      loading="lazy"
      onError={() => setFailed(true)}
      className="h-auto max-h-[30rem] w-auto max-w-full rounded-lg object-contain"
    />
  );
  if (linked) return image;

  return (
    <>
      <span
        ref={triggerRef}
        role="button"
        tabIndex={0}
        aria-label={alt || tFiles("inMessageImage.viewFullImage.label")}
        onClick={() => setFullImageShowing(true)}
        onKeyDown={clickOnKeyDown(() => setFullImageShowing(true))}
        className="block w-fit max-w-full cursor-zoom-in"
      >
        {image}
      </span>
      {fullImageShowing && (
        <FullImageModal
          src={src}
          alt={alt}
          open
          onOpenChange={setFullImageShowing}
          onCloseAutoFocus={(event) => {
            if (!triggerRef.current) return;
            event.preventDefault();
            triggerRef.current.focus();
          }}
        />
      )}
    </>
  );
}

export const stripPartialCitations = (content: string): string =>
  content
    .replace(/\[\[\d+\]\]\([^)]*$/, "")
    // A lone [[ or [[N] or [[N]] at the very end, before the URL arrives.
    .replace(/\[\[(?:\d+\]?\]?)?$/, "");

export const processContent = (content: string): string => {
  content = stripPartialCitations(content);

  // Escape a trailing unclosed `$$` so remark-math skips it mid-stream and
  // the user sees the LaTeX source streaming as plain text. The block swaps
  // to a rendered formula the moment the closing `$$` arrives.
  content = escapeIncompleteBlockMath(content);

  content = labelBareCodeFences(content);

  const processed = preprocessLaTeX(content);
  return escapeIncompleteInlineMath(processed);
};

/**
 * Hook that provides markdown component callbacks for consistent rendering
 */
export const useMarkdownComponents = (
  state: FullChatState | undefined,
  processedContent: string,
  paragraphFont?: TextFont,
  paragraphColor?: TextColor
) => {
  const paragraphCallback = useCallback(
    (props: React.ComponentProps<"p"> & ExtraProps) => (
      <MemoizedParagraph
        dir={props.dir}
        font={paragraphFont}
        color={paragraphColor}
      >
        {props.children}
      </MemoizedParagraph>
    ),
    [paragraphFont, paragraphColor]
  );

  const anchorCallback = useCallback(
    (props: React.ComponentProps<"a"> & ExtraProps) => {
      const imageFileId = extractChatImageFileId(
        props.href,
        String(props.children ?? "")
      );
      if (imageFileId) {
        return (
          <InMessageImage
            fileId={imageFileId}
            fileName={String(props.children ?? "")}
          />
        );
      }
      return (
        <MarkdownLinkContent>
          <MemoizedAnchor
            updatePresentingDocument={
              state?.setPresentingDocument || (() => {})
            }
            docs={state?.docs || []}
            userFiles={state?.userFiles || []}
            citations={state?.citations}
            href={props.href}
          >
            {props.children}
          </MemoizedAnchor>
        </MarkdownLinkContent>
      );
    },
    [
      state?.docs,
      state?.userFiles,
      state?.citations,
      state?.setPresentingDocument,
    ]
  );

  const markdownComponents = useMemo<Components>(
    () => ({
      a: anchorCallback,
      img: MarkdownImage,
      p: paragraphCallback,
      pre: ({ node, className, children }) => {
        // Don't render the pre wrapper - CodeBlock handles its own wrapper
        return <>{children}</>;
      },
      b: ({ node, className, children }) => {
        return <span className={className}>{children}</span>;
      },
      ul: ({ node, className, children, ...props }) => {
        return (
          <ul className={className} {...props}>
            {children}
          </ul>
        );
      },
      ol: ({ node, className, children, ...props }) => {
        return (
          <ol className={className} {...props}>
            {children}
          </ol>
        );
      },
      li: ({ node, className, children, ...props }) => {
        return (
          <li className={className} {...props}>
            {children}
          </li>
        );
      },
      table: ({ node, className, children, ...props }) => {
        return (
          <ScrollableTable
            className={className}
            getCopyContent={
              node
                ? () =>
                    tableToCopyContent(
                      node,
                      createCitationResolver(state?.docs, state?.citations)
                    )
                : undefined
            }
            {...props}
          >
            {children}
          </ScrollableTable>
        );
      },
      code: ({ node, className, children }) => {
        const codeText = extractCodeText(node, processedContent, children);

        return (
          <CodeBlock className={className} codeText={codeText}>
            {children}
          </CodeBlock>
        );
      },
    }),
    [
      anchorCallback,
      paragraphCallback,
      processedContent,
      state?.docs,
      state?.citations,
    ]
  );

  return markdownComponents;
};

/**
 * Renders markdown content with consistent configuration
 */
export const renderMarkdown = (
  content: string,
  markdownComponents: Components,
  textSize: string = "text-base",
  languages: Record<string, LanguageFn> | null = null
): JSX.Element => {
  return (
    <div dir="auto">
      <ReactMarkdown
        className={cn(
          "response-text prose dark:prose-invert font-main-content-body max-w-full",
          textSize
        )}
        components={markdownComponents}
        remarkPlugins={[
          remarkGfm,
          [remarkMath, { singleDollarTextMath: true }],
        ]}
        rehypePlugins={
          languages
            ? [[rehypeHighlight, { languages }], rehypeKatex, rehypeDirection]
            : [rehypeKatex, rehypeDirection]
        }
        urlTransform={transformLinkUri}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
};

/**
 * Complete markdown processing and rendering utility
 */
export const useMarkdownRenderer = (
  content: string,
  state: FullChatState | undefined,
  textSize: string
) => {
  const processedContent = useMemo(() => processContent(content), [content]);
  const markdownComponents = useMarkdownComponents(state, processedContent);
  const highlightLanguages = useHighlightLanguages();

  const renderedContent = useMemo(
    () =>
      renderMarkdown(
        processedContent,
        markdownComponents,
        textSize,
        highlightLanguages
      ),
    [processedContent, markdownComponents, textSize, highlightLanguages]
  );

  return {
    processedContent,
    markdownComponents,
    renderedContent,
  };
};
