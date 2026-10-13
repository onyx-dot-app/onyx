"use client";

import {
  useState,
  useRef,
  useEffect,
  useCallback,
  useEffectEvent,
} from "react";
import { Document, Page, pdfjs } from "react-pdf";
import type { PDFDocumentProxy, PDFPageProxy } from "pdfjs-dist";
import { useInView } from "motion/react";
import { useTranslations, useFormatter } from "next-intl";
import { Button, Dropdown, SelectCard, Text } from "@opal/components";
import {
  SvgZoomIn,
  SvgZoomOut,
  SvgChevronDown,
  SvgDownloadCloud,
} from "@opal/icons";
import DocumentPreviewControls from "@/app/craft/components/output-panel/DocumentPreviewControls";
import PreviewSidebar from "@/app/craft/components/output-panel/PreviewSidebar";
import { WorkspaceHome } from "@/app/craft/components/output-panel/WorkspaceHome";
import "react-pdf/dist/Page/TextLayer.css";
import "react-pdf/dist/Page/AnnotationLayer.css";

const assetRoot = `/pdfjs/${pdfjs.version}/`;
pdfjs.GlobalWorkerOptions.workerSrc = `${assetRoot}pdf.worker.min.mjs`;
const DOCUMENT_OPTIONS = {
  cMapUrl: `${assetRoot}cmaps/`,
  cMapPacked: true,
  standardFontDataUrl: `${assetRoot}standard_fonts/`,
  wasmUrl: `${assetRoot}wasm/`,
  iccUrl: `${assetRoot}iccs/`,
  isEvalSupported: false,
};
const ZOOM_LEVELS = [0.5, 0.75, 1, 1.25, 1.5, 2, 3];
interface PdfDocumentViewerProps {
  blob: Blob;
  isActive: boolean;
  initialPage?: number;
  onDownload: () => void;
  onPageChange?: (page: number) => void;
}
type Zoom = "width" | "page" | number;

export default function PdfDocumentViewer({
  blob,
  isActive,
  initialPage = 1,
  onPageChange,
  onDownload,
}: PdfDocumentViewerProps) {
  const t = useTranslations("craft.pdfPreview");
  const format = useFormatter();
  const downloadTranslations = useTranslations("craft.filesTab");
  const [documentState, setDocumentState] = useState<{
    blob: Blob;
    pdf: PDFDocumentProxy | null;
    failed: boolean;
    generation: number;
    pageNumber: number;
    pageSize: { width: number; height: number };
  }>({
    blob,
    pdf: null,
    failed: false,
    generation: 0,
    pageNumber: initialPage,
    pageSize: { width: 612, height: 792 },
  });
  if (documentState.blob !== blob) {
    setDocumentState({
      ...documentState,
      blob,
      pdf: null,
      failed: false,
      generation: documentState.generation + 1,
    });
  }
  const { pdf, failed, generation, pageNumber, pageSize } = documentState;
  const [zoom, setZoom] = useState<Zoom>("width");
  const [showThumbnails, setShowThumbnails] = useState(true);
  const viewportRef = useRef<HTMLDivElement>(null);
  const [viewportSize, setViewportSize] = useState({ width: 0, height: 0 });
  const pageCount = pdf?.numPages ?? 0;
  const activePage = Math.max(1, Math.min(pageNumber, pageCount || 1));
  const availableWidth = Math.max(1, viewportSize.width);
  const availableHeight = Math.max(1, viewportSize.height);
  const fitWidth = availableWidth / pageSize.width;
  const scale =
    typeof zoom === "number"
      ? zoom
      : zoom === "width"
        ? fitWidth
        : Math.min(fitWidth, availableHeight / pageSize.height);
  const loading = (
    <Text font="secondary-body" color="text-03">
      {t("loading.label")}
    </Text>
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
  const reportPage = useEffectEvent(() => onPageChange?.(activePage));
  useEffect(() => {
    if (pageCount) reportPage();
  }, [activePage, pageCount]);
  useEffect(() => {
    viewportRef.current?.scrollTo?.({ top: 0, left: 0 });
  }, [activePage]);

  function loadDocument(document: PDFDocumentProxy) {
    setDocumentState((current) =>
      current.blob === blob
        ? {
            ...current,
            pdf: document,
            failed: false,
            pageNumber: Math.max(
              1,
              Math.min(current.pageNumber, document.numPages)
            ),
          }
        : current
    );
  }
  function selectPage(page: number) {
    setDocumentState((current) =>
      current.blob === blob
        ? {
            ...current,
            pageNumber: Math.max(1, Math.min(page, current.pdf?.numPages ?? 1)),
          }
        : current
    );
  }
  function failDocument() {
    setDocumentState((current) =>
      current.blob === blob ? { ...current, failed: true } : current
    );
  }
  function loadPage(page: PDFPageProxy) {
    const viewport = page.getViewport({ scale: 1 });
    setDocumentState((current) =>
      current.blob !== blob ||
      Math.max(1, Math.min(current.pageNumber, current.pdf?.numPages ?? 1)) !==
        page.pageNumber ||
      (current.pageSize.width === viewport.width &&
        current.pageSize.height === viewport.height)
        ? current
        : {
            ...current,
            pageSize: { width: viewport.width, height: viewport.height },
          }
    );
  }
  function zoomBy(delta: number) {
    setZoom(
      Math.max(0.25, Math.min(3, Math.round((scale + delta) * 100) / 100))
    );
  }
  const zoomLabel = (value: Zoom) =>
    typeof value === "number"
      ? format.number(value, { style: "percent", maximumFractionDigits: 0 })
      : t(value === "width" ? "zoom.fitWidth" : "zoom.fitPage");

  if (failed)
    return (
      <WorkspaceHome title={t("error.title")}>
        <div className="flex flex-col items-center gap-3 text-center">
          <Text font="secondary-body" color="text-03">
            {t("error.description")}
          </Text>
          <Button
            icon={SvgDownloadCloud}
            size="sm"
            prominence="secondary"
            onClick={onDownload}
          >
            {downloadTranslations("download.label")}
          </Button>
        </div>
      </WorkspaceHome>
    );

  return (
    <Document
      file={blob}
      options={DOCUMENT_OPTIONS}
      suspense={false}
      onLoadSuccess={loadDocument}
      onLoadError={failDocument}
      onSourceError={failDocument}
      onPassword={failDocument}
      onItemClick={({ pageNumber: target }) => {
        if (target) selectPage(target);
      }}
      externalLinkTarget="_blank"
      externalLinkRel="noopener noreferrer"
      className="flex h-full min-h-0 flex-col"
      loading={
        <WorkspaceHome title={t("loading.label")}>
          <></>
        </WorkspaceHome>
      }
      error={
        <WorkspaceHome title={t("error.title")}>
          <Text font="secondary-body" color="text-03">
            {t("error.description")}
          </Text>
        </WorkspaceHome>
      }
    >
      {pageCount > 0 && (
        <>
          <DocumentPreviewControls
            label={t("controls.label")}
            previousLabel={t("page.previous")}
            nextLabel={t("page.next")}
            thumbnailsLabel={t("thumbnails.toggle")}
            counter={t("page.counter", {
              current: activePage,
              total: pageCount,
            })}
            page={activePage}
            pageCount={pageCount}
            showThumbnails={showThumbnails}
            onToggleThumbnails={() => setShowThumbnails((value) => !value)}
            onPageChange={selectPage}
          >
            <div className="flex items-center gap-0.5">
              <Button
                icon={SvgZoomOut}
                size="xs"
                prominence="tertiary"
                aria-label={t("zoom.out")}
                disabled={scale <= 0.25}
                onClick={() => zoomBy(-0.25)}
              />
              <Dropdown align="end">
                <Dropdown.Trigger asChild>
                  <Button
                    size="xs"
                    prominence="tertiary"
                    rightIcon={SvgChevronDown}
                    aria-label={t("zoom.label")}
                  >
                    {zoomLabel(zoom)}
                  </Button>
                </Dropdown.Trigger>
                <Dropdown.Data
                  label={t("zoom.label")}
                  value={String(zoom)}
                  items={["width", "page", ...ZOOM_LEVELS].map((value) => ({
                    kind: "option",
                    value: String(value),
                    title: zoomLabel(
                      typeof value === "number"
                        ? value
                        : value === "width"
                          ? "width"
                          : "page"
                    ),
                  }))}
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
                aria-label={t("zoom.in")}
                disabled={scale >= 3}
                onClick={() => zoomBy(0.25)}
              />
            </div>
          </DocumentPreviewControls>
          <div className="flex min-h-0 flex-1 overflow-hidden">
            <PreviewSidebar
              hidden={!showThumbnails}
              label={t("thumbnails.resize")}
            >
              {(width) => (
                <div
                  className="h-full overflow-y-auto overscroll-contain p-2"
                  aria-label={t("thumbnails.label")}
                >
                  <div className="flex flex-col gap-2">
                    {Array.from({ length: pageCount }, (_, index) => (
                      <PdfThumbnail
                        key={`${generation}:${index + 1}`}
                        page={index + 1}
                        active={activePage === index + 1}
                        width={Math.max(40, width - 24)}
                        isActive={isActive}
                        onSelect={() => selectPage(index + 1)}
                      />
                    ))}
                  </div>
                </div>
              )}
            </PreviewSidebar>
            <div
              ref={observeViewport}
              className="min-w-0 flex-1 overflow-auto bg-background-neutral-02 p-4"
              role="region"
              // oxlint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- Focus lets keyboard users scroll the PDF viewport.
              tabIndex={isActive ? 0 : -1}
              aria-label={t("page.preview", { page: activePage })}
            >
              <div className="flex w-max min-w-full justify-center">
                <Page
                  pageNumber={activePage}
                  scale={scale}
                  suspense={false}
                  onLoadSuccess={loadPage}
                  loading={loading}
                  error={
                    <Text font="secondary-body" color="text-03">
                      {t("error.description")}
                    </Text>
                  }
                  className="shrink-0 shadow-sm"
                />
              </div>
            </div>
          </div>
        </>
      )}
    </Document>
  );
}

function PdfThumbnail({
  page,
  active,
  width,
  isActive,
  onSelect,
}: {
  page: number;
  active: boolean;
  width: number;
  isActive: boolean;
  onSelect: () => void;
}) {
  const t = useTranslations("craft.pdfPreview");
  const format = useFormatter();
  const ref = useRef<HTMLDivElement>(null);
  const visible = useInView(ref, { margin: "100px" });
  const [rendered, setRendered] = useState(false);
  const shouldRender = rendered || (isActive && (visible || active));
  useEffect(() => {
    if (active && isActive) ref.current?.scrollIntoView?.({ block: "nearest" });
  }, [active, isActive]);
  return (
    <SelectCard
      ref={ref}
      role="button"
      tabIndex={0}
      aria-label={t("page.select", { page })}
      aria-current={active ? "page" : undefined}
      state={active ? "selected" : "empty"}
      padding={1}
      rounding={2}
      onClick={onSelect}
    >
      <div className="flex flex-col gap-1">
        <div className="flex aspect-[3/4] items-center justify-center overflow-hidden bg-background-neutral-00">
          {shouldRender && (
            <Page
              pageNumber={page}
              width={width}
              suspense={false}
              renderTextLayer={false}
              renderAnnotationLayer={false}
              devicePixelRatio={1}
              onRenderSuccess={() => setRendered(true)}
              loading={null}
              error={null}
            />
          )}
        </div>
        <Text font="secondary-body" color="text-03">
          {format.number(page)}
        </Text>
      </div>
    </SelectCard>
  );
}
