"use client";

import {
  memo,
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import dynamic from "next/dynamic";
import { SWRConfig } from "swr";
import { useTranslations } from "next-intl";
import { Button, CopyButton, OnyxLoader, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import { SvgCode, SvgEye } from "@opal/icons";
import type { RichStr } from "@opal/types";
import type { ChatFilePreviewState } from "@/lib/filePreview/hooks";
import { resolveFilePreviewFormat, svgDataUrl } from "@/lib/filePreview/format";
import FloatingFooter from "@/sections/file-preview/FloatingFooter";
import { DownloadButton } from "@/sections/file-preview/DownloadButton";
import { PreviewUnavailable } from "@/sections/file-preview/PreviewUnavailable";
import { CodeFilePreview } from "@/sections/file-preview/CodeFilePreview";
import { MarkdownFilePreview } from "@/sections/file-preview/MarkdownFilePreview";
import { SpreadsheetPreview } from "@/sections/file-preview/SpreadsheetPreview";
import { ImagePreview } from "@/sections/file-preview/ImagePreview";

// An HTML preview is a static page: its inline styles and its data or blob
// images, fonts and media. No script runs and nothing loads from the network,
// so a page cannot send its contents to another site. Without scripts the
// sandbox also refuses a meta refresh, the one way a static page navigates
// itself without a click.
const HTML_PREVIEW_POLICY =
  "default-src 'none'; script-src 'none'; style-src 'unsafe-inline'; img-src data: blob:; font-src data:; media-src data: blob:; form-action 'none'";

// A fixed prologue, so no text in the file can move the policy: before any
// of the file's content, the parser puts the meta in the document's head.
// Its own doctype keeps the page out of quirks mode; a later doctype in the
// file is ignored.
const HTML_PREVIEW_PROLOGUE = `<!DOCTYPE html><meta http-equiv="Content-Security-Policy" content="${HTML_PREVIEW_POLICY}">`;

// A fast load shows nothing; a slower one shows the loader
const LOADER_DELAY_MS = 300;

const MAX_RENDERED_MARKDOWN_CHARACTERS = 200_000;

interface LoadingProps {
  // A line under the loader, read out by screen readers
  status?: string | RichStr;
}

function Loading({ status }: LoadingProps) {
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    const timer = window.setTimeout(() => setVisible(true), LOADER_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, []);
  return (
    <Section gap={1}>
      {visible && <OnyxLoader size={32} />}
      <div aria-live="polite">
        {visible && status && (
          <Text as="p" font="secondary-body" color="text-03">
            {status}
          </Text>
        )}
      </div>
    </Section>
  );
}

// PDF.js loads only when a PDF opens
const PdfViewer = dynamic(() => import("@/sections/file-preview/PdfViewer"), {
  ssr: false,
  loading: () => <Loading />,
});

/**
 * Gives a preview its own SWR cache, so a file's bytes go when its preview
 * closes. Wrap each `useChatFilePreview` caller in it.
 */
export function FilePreviewScope({ children }: { children: ReactNode }) {
  const value = useMemo(() => ({ provider: () => new Map() }), []);
  return <SWRConfig value={value}>{children}</SWRConfig>;
}

interface FilePreviewBodyProps {
  preview: ChatFilePreviewState;
  fileName: string;
}

/**
 * A chat file's preview, below a header that the host draws: the content for
 * its format, with its actions over its bottom or in a slot the host gives
 * (`PreviewActionsSlotContext`). Markdown, CSV, HTML and SVG
 * show rendered, with a toggle to their source. The chat's right panel and
 * the preview modal both show files through it. A file that does not load or
 * render shows one card with its download instead.
 */
export const FilePreviewBody = memo(function FilePreviewBody({
  preview,
  fileName,
}: FilePreviewBodyProps) {
  const t = useTranslations("chat.filePreview");
  const { data, error, isLoading, retry } = preview;
  const [renderFailed, setRenderFailed] = useState(false);
  const [showSource, setShowSource] = useState(false);
  const failRender = useCallback(() => setRenderFailed(true), []);

  let content: ReactNode;
  let footer: ReactNode = null;
  if (isLoading || (!data && !error)) {
    // The server converts a Word or PowerPoint file on its first preview,
    // which can take much longer than a download
    content = (
      <Loading
        status={
          resolveFilePreviewFormat(fileName, "application/octet-stream")
            .kind === "office"
            ? t("preparing.status")
            : undefined
        }
      />
    );
  } else if (!data) {
    content = (
      <PreviewUnavailable
        fileName={fileName}
        fileUrl={preview.url}
        title={t("error.title")}
        description={t("error.description")}
        onRetry={retry}
      />
    );
  } else if (data.kind === "unavailable") {
    content = (
      <PreviewUnavailable
        fileName={data.name}
        fileUrl={preview.url}
        title={t("unavailable.title")}
        description={t("unavailable.description")}
      />
    );
  } else if (renderFailed) {
    content = (
      <PreviewUnavailable
        fileName={data.name}
        fileUrl={preview.url}
        title={t("renderError.title")}
        description={t("renderError.description")}
      />
    );
  } else {
    const download = (
      <DownloadButton fileUrl={preview.url} fileName={data.name} />
    );
    const switchLabel = t(
      showSource ? "previewButton.tooltip" : "sourceButton.tooltip"
    );
    const textActions = (text: string, rendered = false) => (
      <Section flexDirection="row" width="fit" gap={0}>
        {rendered && (
          // Names the view it switches to: the source, or back to the preview
          <Button
            icon={showSource ? SvgEye : SvgCode}
            prominence="tertiary"
            size="md"
            tooltip={switchLabel}
            aria-label={switchLabel}
            onClick={() => setShowSource((value) => !value)}
          />
        )}
        <CopyButton
          size="md"
          tooltip={t("copyButton.tooltip")}
          aria-label={t("copyButton.tooltip")}
          getCopyText={() => text}
        />
        {download}
      </Section>
    );
    switch (data.kind) {
      case "code": {
        const actions = textActions(data.text, data.render !== undefined);
        if (data.render === "svg" && !showSource) {
          content = (
            <ImagePreview
              src={svgDataUrl(data.text)}
              fileName={data.name}
              actions={actions}
              // A drawing the browser cannot render still shows its source
              onError={() => setShowSource(true)}
            />
          );
        } else if (data.render === "html" && !showSource) {
          // An empty sandbox: an opaque origin, no scripts, no forms, popups
          // or navigation of the chat page
          content = (
            <iframe
              title={data.name}
              srcDoc={HTML_PREVIEW_PROLOGUE + data.text}
              sandbox=""
              referrerPolicy="no-referrer"
              className="h-full w-full border-0 bg-background-neutral-00"
            />
          );
          footer = <FloatingFooter right={actions} />;
        } else {
          content = (
            <CodeFilePreview text={data.text} language={data.language} />
          );
          footer = (
            <FloatingFooter
              codeBackground
              left={
                <Text as="p" font="main-ui-body" color="text-03">
                  {t("lineCount.label", { count: data.lineCount })}
                </Text>
              }
              right={actions}
            />
          );
        }
        break;
      }
      case "markdown": {
        // Long markdown shows as source, which renders in linear time
        const tooLong = data.text.length > MAX_RENDERED_MARKDOWN_CHARACTERS;
        const source = tooLong || showSource;
        content = source ? (
          <CodeFilePreview text={data.text} language="plaintext" />
        ) : (
          <MarkdownFilePreview text={data.text} />
        );
        footer = (
          <FloatingFooter
            codeBackground={source}
            right={textActions(data.text, !tooLong)}
          />
        );
        break;
      }
      case "csv": {
        const csv = data.sheets[0].csv;
        content = showSource ? (
          <CodeFilePreview text={csv} language="plaintext" />
        ) : (
          <SpreadsheetPreview sheets={data.sheets} />
        );
        footer = (
          <FloatingFooter
            codeBackground={showSource}
            right={textActions(csv, true)}
          />
        );
        break;
      }
      case "spreadsheet":
        content = <SpreadsheetPreview sheets={data.sheets} />;
        footer = <FloatingFooter right={download} />;
        break;
      case "pdf":
        content = <PdfViewer blob={data.blob} onError={failRender} />;
        footer = <FloatingFooter right={download} />;
        break;
      case "image":
        content = (
          <ImagePreview
            src={preview.url}
            fileName={data.name}
            actions={download}
            onError={failRender}
          />
        );
        break;
      case "tooLarge":
        content = (
          <PreviewUnavailable
            fileName={data.name}
            fileUrl={preview.url}
            title={t("tooLarge.title")}
            description={t("tooLarge.description", { size: data.limitMB })}
          />
        );
        break;
      case "unsupported":
        content = (
          <PreviewUnavailable
            fileName={data.name}
            fileUrl={preview.url}
            title={t("unsupported.title")}
            description={t("unsupported.description")}
          />
        );
        break;
    }
  }

  return (
    <Section
      gap={0}
      justifyContent="start"
      alignItems="stretch"
      // Its own stacking context, so no preview paints over the host's
      // controls, such as the panel's resize handle
      className="relative isolate min-h-0 flex-1 overflow-hidden"
    >
      {content}
      {footer}
    </Section>
  );
});
