"use client";

import {
  memo,
  useCallback,
  useEffect,
  useRef,
  useState,
  type RefObject,
} from "react";
import { Document, Page } from "react-pdf";
import type { PDFDocumentProxy } from "pdfjs-dist";
import { useInView } from "motion/react";
import { useFormatter, useTranslations } from "next-intl";
import {
  Button,
  Dropdown,
  OnyxLoader,
  SelectCard,
  Text,
} from "@opal/components";
import { Section } from "@opal/layouts";
import {
  DocumentToolbar,
  PreviewSidebar,
} from "@/sections/file-preview/PreviewControls";
import { SvgChevronDown, SvgZoomIn, SvgZoomOut } from "@opal/icons";
import "react-pdf/dist/Page/TextLayer.css";
import "react-pdf/dist/Page/AnnotationLayer.css";
import { PDF_DOCUMENT_OPTIONS } from "@/lib/filePreview/pdfjs";

const ZOOM_LEVELS = [0.5, 0.75, 1, 1.25, 1.5, 2, 3];
const MIN_ZOOM = 0.25;
const MAX_ZOOM = 3;
// The thumbnail column's starting width, and its padding and the card's
// around a thumbnail
const THUMBNAIL_COLUMN_WIDTH = 144;
const THUMBNAIL_INSET = 24;

type Zoom = "width" | "page" | number;

interface PdfThumbnailProps {
  page: number;
  width: number;
  active: boolean;
  // The thumbnail column, which scrolls
  column: RefObject<HTMLDivElement | null>;
  onSelect: (page: number) => void;
}

/**
 * A page's thumbnail, drawn once it nears the column's view and dropped when
 * it scrolls far out of it, so a long document keeps few pages drawn. A
 * hidden column, as in a hidden tab, keeps the thumbnails it has drawn.
 */
const PdfThumbnail = memo(function PdfThumbnail({
  page,
  width,
  active,
  column,
  onSelect,
}: PdfThumbnailProps) {
  const t = useTranslations("chat.filePreview");
  const format = useFormatter();
  const ref = useRef<HTMLDivElement>(null);
  const near = useInView(ref, { root: column, margin: "400px 0px" }) || active;
  const [drawn, setDrawn] = useState(near);
  if (near && !drawn) setDrawn(true);

  useEffect(() => {
    // A hidden column reports every thumbnail out of view
    if (!near && column.current?.checkVisibility()) setDrawn(false);
  }, [near, column]);

  useEffect(() => {
    if (active) ref.current?.scrollIntoView({ block: "nearest" });
  }, [active]);

  return (
    <SelectCard
      ref={ref}
      role="button"
      tabIndex={0}
      aria-label={t("pdf.page.select", { page })}
      aria-current={active ? "page" : undefined}
      state={active ? "selected" : "empty"}
      padding={1}
      rounding={2}
      onClick={() => onSelect(page)}
    >
      <Section gap={1} height="auto">
        <Section
          height="auto"
          gap={0}
          className="aspect-[3/4] overflow-hidden bg-background-neutral-00"
        >
          {drawn && (
            <Page
              pageNumber={page}
              width={width}
              suspense={false}
              renderTextLayer={false}
              renderAnnotationLayer={false}
              devicePixelRatio={1}
              loading={null}
              error={null}
            />
          )}
        </Section>
        <Text as="p" font="secondary-body" color="text-03">
          {format.number(page)}
        </Text>
      </Section>
    </SelectCard>
  );
});

interface PdfViewerProps {
  blob: Blob;
  // The file is password-protected or broken
  onError: () => void;
}

/**
 * A PDF one page at a time, drawn by PDF.js: page thumbnails in a column
 * that the user can hide, page buttons, and zoom to fit the width, fit the
 * page or a set level. Links open in a new tab.
 */
export default function PdfViewer({ blob, onError }: PdfViewerProps) {
  const t = useTranslations("chat.filePreview");
  const format = useFormatter();
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null);
  const [pageNumber, setPageNumber] = useState(1);
  const [pageSize, setPageSize] = useState({ width: 612, height: 792 });
  const [zoom, setZoom] = useState<Zoom>("width");
  const [showThumbnails, setShowThumbnails] = useState(true);
  const viewportRef = useRef<HTMLDivElement>(null);
  const thumbnailColumn = useRef<HTMLDivElement>(null);
  const [viewportSize, setViewportSize] = useState({ width: 0, height: 0 });

  const pageCount = pdf?.numPages ?? 0;
  const fitWidth = Math.max(1, viewportSize.width) / pageSize.width;
  const scale =
    typeof zoom === "number"
      ? zoom
      : zoom === "width"
        ? fitWidth
        : Math.min(
            fitWidth,
            Math.max(1, viewportSize.height) / pageSize.height
          );

  const observeViewport = useCallback((viewport: HTMLDivElement | null) => {
    viewportRef.current = viewport;
    if (!viewport) return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry && entry.contentRect.width > 0 && entry.contentRect.height > 0)
        setViewportSize({
          width: entry.contentRect.width,
          height: entry.contentRect.height,
        });
    });
    // oxlint-disable-next-line react-doctor/effect-needs-cleanup -- React calls this ref's returned disposer on detachment.
    observer.observe(viewport);
    return () => {
      observer.disconnect();
      viewportRef.current = null;
    };
  }, []);

  useEffect(() => {
    viewportRef.current?.scrollTo({ top: 0, left: 0 });
  }, [pageNumber]);

  // Stable, so a page change renders only the thumbnails that change
  const selectPage = useCallback(
    (page: number) =>
      setPageNumber(Math.max(1, Math.min(page, pageCount || 1))),
    [pageCount]
  );

  function zoomBy(delta: number) {
    setZoom(
      Math.max(
        MIN_ZOOM,
        Math.min(MAX_ZOOM, Math.round((scale + delta) * 100) / 100)
      )
    );
  }

  function zoomLabel(value: Zoom) {
    return typeof value === "number"
      ? format.number(value, { style: "percent", maximumFractionDigits: 0 })
      : t(value === "width" ? "pdf.zoom.fitWidth" : "pdf.zoom.fitPage");
  }

  const loader = (
    <Section>
      <OnyxLoader size={32} />
    </Section>
  );

  return (
    <Document
      file={blob}
      options={PDF_DOCUMENT_OPTIONS}
      suspense={false}
      onLoadSuccess={(document) => setPdf(document)}
      onLoadError={onError}
      onSourceError={onError}
      onPassword={onError}
      onItemClick={({ pageNumber: target }) => {
        if (target) selectPage(target);
      }}
      externalLinkTarget="_blank"
      externalLinkRel="noopener noreferrer"
      className="flex h-full min-h-0 flex-col"
      loading={loader}
      error={null}
    >
      {pageCount > 0 && (
        <>
          <DocumentToolbar
            label={t("pdf.controls.label")}
            thumbnailsLabel={t("pdf.thumbnails.toggle")}
            previousLabel={t("pdf.page.previous")}
            nextLabel={t("pdf.page.next")}
            counter={t("pdf.page.counter", {
              current: pageNumber,
              total: pageCount,
            })}
            page={pageNumber}
            pageCount={pageCount}
            showThumbnails={showThumbnails}
            onToggleThumbnails={() => setShowThumbnails((value) => !value)}
            onPageChange={selectPage}
          >
            <Section flexDirection="row" width="fit" gap={0.5}>
              <Button
                icon={SvgZoomOut}
                size="xs"
                prominence="tertiary"
                aria-label={t("pdf.zoom.out")}
                disabled={scale <= MIN_ZOOM}
                onClick={() => zoomBy(-0.25)}
              />
              <Dropdown align="end">
                <Dropdown.Trigger asChild>
                  <Button
                    size="xs"
                    prominence="tertiary"
                    rightIcon={SvgChevronDown}
                    aria-label={t("pdf.zoom.label")}
                  >
                    {zoomLabel(zoom)}
                  </Button>
                </Dropdown.Trigger>
                <Dropdown.Data
                  label={t("pdf.zoom.label")}
                  value={String(zoom)}
                  items={(["width", "page", ...ZOOM_LEVELS] as const).map(
                    (value) => ({
                      kind: "option" as const,
                      value: String(value),
                      title: zoomLabel(value),
                    })
                  )}
                  onSelect={(option) =>
                    setZoom(
                      option.value === "width" || option.value === "page"
                        ? option.value
                        : Number(option.value)
                    )
                  }
                />
              </Dropdown>
              <Button
                icon={SvgZoomIn}
                size="xs"
                prominence="tertiary"
                aria-label={t("pdf.zoom.in")}
                disabled={scale >= MAX_ZOOM}
                onClick={() => zoomBy(0.25)}
              />
            </Section>
          </DocumentToolbar>
          <Section
            flexDirection="row"
            alignItems="stretch"
            gap={0}
            className="overflow-hidden"
          >
            <PreviewSidebar
              label={t("pdf.thumbnails.resize")}
              initialWidth={THUMBNAIL_COLUMN_WIDTH}
              hidden={!showThumbnails}
            >
              {(width) => (
                <div
                  ref={thumbnailColumn}
                  className="h-full overflow-y-auto overscroll-contain p-2"
                  aria-label={t("pdf.thumbnails.label")}
                >
                  <Section gap={2} height="auto">
                    {Array.from({ length: pageCount }, (_, index) => (
                      <PdfThumbnail
                        key={index + 1}
                        page={index + 1}
                        width={Math.max(40, width - THUMBNAIL_INSET)}
                        active={pageNumber === index + 1}
                        column={thumbnailColumn}
                        onSelect={selectPage}
                      />
                    ))}
                  </Section>
                </div>
              )}
            </PreviewSidebar>
            <div
              ref={observeViewport}
              // A stable gutter keeps fit-width from changing with the scrollbar
              className="min-w-0 flex-1 overflow-auto bg-background-neutral-02 p-4 pb-16 [scrollbar-gutter:stable]"
              role="region"
              // oxlint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- Focus lets keyboard users scroll the page.
              tabIndex={0}
              aria-label={t("pdf.page.preview", { page: pageNumber })}
            >
              <Section
                flexDirection="row"
                width="fit"
                height="auto"
                className="min-w-full"
              >
                <Page
                  pageNumber={pageNumber}
                  scale={scale}
                  suspense={false}
                  onLoadSuccess={(page) => {
                    const viewport = page.getViewport({ scale: 1 });
                    setPageSize((current) =>
                      current.width === viewport.width &&
                      current.height === viewport.height
                        ? current
                        : { width: viewport.width, height: viewport.height }
                    );
                  }}
                  loading={loader}
                  error={
                    <Text as="p" font="secondary-body" color="text-03">
                      {t("pdf.error.description")}
                    </Text>
                  }
                  className="shrink-0 shadow-sm"
                />
              </Section>
            </div>
          </Section>
        </>
      )}
    </Document>
  );
}
