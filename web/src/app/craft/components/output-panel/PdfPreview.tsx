"use client";

import { useState, useEffect, useRef } from "react";
import type { PDFViewer } from "pdfjs-dist/web/pdf_viewer.mjs";
import "pdfjs-dist/web/pdf_viewer.css";
import useSWR from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import { useTranslations } from "next-intl";
import { Button, Text } from "@opal/components";
import {
  SvgFileText,
  SvgChevronLeft,
  SvgChevronRight,
  SvgMinus,
  SvgPlus,
} from "@opal/icons";
import { Section } from "@/layouts/general-layouts";
import { buildArtifactUrl } from "@/app/craft/services/apiServices";

interface PdfPreviewProps {
  sessionId: string;
  filePath: string;
  revision?: string;
  refreshKey?: number;
}

export default function PdfPreview({
  sessionId,
  filePath,
  revision,
  refreshKey,
}: PdfPreviewProps) {
  const t = useTranslations("craft.pdfPreview");
  const {
    data: blob,
    error,
    isLoading,
  } = useSWR(
    [
      SWR_KEYS.buildSessionArtifactFile(sessionId, filePath),
      "pdf",
      revision,
      refreshKey ?? 0,
    ],
    async () => {
      const response = await fetch(buildArtifactUrl(sessionId, filePath), {
        cache: "no-store",
      });
      if (!response.ok)
        throw new Error(`Failed to fetch PDF: ${response.status}`);
      return response.blob();
    },
    {
      revalidateOnFocus: false,
      revalidateOnReconnect: false,
      revalidateIfStale: revision === undefined,
    }
  );
  if (error) return <PdfError />;
  if (isLoading || !blob) return <PdfLoading />;

  // Remount each document; cached bytes survive, but PDF.js owns its worker lifecycle.
  return (
    <PdfDocument
      key={`${sessionId}:${filePath}:${revision}:${refreshKey}`}
      blob={blob}
      filePath={filePath}
    />
  );
}

function PdfDocument({ blob, filePath }: { blob: Blob; filePath: string }) {
  const t = useTranslations("craft.pdfPreview");
  const containerRef = useRef<HTMLDivElement>(null);
  const pagesRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<PDFViewer | null>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState(false);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);

  useEffect(() => {
    const container = containerRef.current;
    const pages = pagesRef.current;
    if (!container || !pages) return;
    const controller = new AbortController();
    let dispose: (() => void) | undefined;
    setReady(false);
    setError(false);

    async function load() {
      if (!container || !pages) return;
      const pdfjs = await import("pdfjs-dist");
      const { PDFViewer, EventBus, PDFLinkService, LinkTarget } =
        await import("pdfjs-dist/web/pdf_viewer.mjs");
      const bytes = await blob.arrayBuffer();
      if (controller.signal.aborted) return;
      const assets = `/pdfjs/${pdfjs.version}`;
      pdfjs.GlobalWorkerOptions.workerSrc = `${assets}/pdf.worker.min.mjs`;
      const eventBus = new EventBus();
      const linkService = new PDFLinkService({
        eventBus,
        externalLinkTarget: LinkTarget.BLANK,
        externalLinkRel: "noopener noreferrer",
      });
      // PDF.js accepts abortSignal, but its published options type omits it.
      const viewerOptions = {
        container,
        viewer: pages,
        eventBus,
        linkService,
        abortSignal: controller.signal,
        annotationMode: pdfjs.AnnotationMode.ENABLE,
        imageResourcesPath: `${assets}/web/images/`,
      };
      const viewer = new PDFViewer(viewerOptions);
      viewerRef.current = viewer;
      linkService.setViewer(viewer);
      eventBus.on("pagesinit", () => {
        viewer.currentScaleValue = "page-width";
        setPage(1);
        setReady(true);
      });
      eventBus.on("pagechanging", ({ pageNumber }: { pageNumber: number }) =>
        setPage(pageNumber)
      );
      eventBus.on(
        "pagerendered",
        ({ error: renderError }: { error?: Error }) => {
          if (renderError) setError(true);
        }
      );
      const task = pdfjs.getDocument({
        // PDF.js transfers this buffer to its worker. SWR retains the original Blob.
        data: bytes,
        cMapUrl: `${assets}/cmaps/`,
        cMapPacked: true,
        standardFontDataUrl: `${assets}/standard_fonts/`,
        wasmUrl: `${assets}/wasm/`,
        iccUrl: `${assets}/iccs/`,
      });
      let previousWidth = container.clientWidth;
      const resizeObserver = new ResizeObserver(() => {
        const width = container.clientWidth;
        if (
          width !== previousWidth &&
          viewer.currentScaleValue === "page-width"
        ) {
          viewer.currentScaleValue = "page-width";
        }
        previousWidth = width;
      });
      resizeObserver.observe(container);
      dispose = () => {
        resizeObserver.disconnect();
        viewer.setDocument(null);
        linkService.setDocument(null);
        viewerRef.current = null;
        void task.destroy();
      };
      const document = await task.promise;
      if (controller.signal.aborted) return;
      setTotal(document.numPages);
      linkService.setDocument(document);
      viewer.setDocument(document);
    }
    void load().catch(() => {
      if (!controller.signal.aborted) {
        controller.abort();
        dispose?.();
        dispose = undefined;
        setError(true);
      }
    });
    return () => {
      controller.abort();
      dispose?.();
    };
  }, [blob]);

  if (error) return <PdfError />;

  return (
    <div className="h-full min-h-0 flex flex-col">
      <div className="flex flex-wrap items-center justify-center gap-2 p-2 border-b border-border-02">
        <Button
          icon={SvgChevronLeft}
          size="sm"
          prominence="tertiary"
          aria-label={t("controls.previous")}
          disabled={!ready || page <= 1}
          onClick={() => {
            if (viewerRef.current)
              viewerRef.current.currentPageNumber = page - 1;
          }}
        />
        <Text font="secondary-body" color="text-03">
          {t("page.counter", { current: page, total })}
        </Text>
        <Button
          icon={SvgChevronRight}
          size="sm"
          prominence="tertiary"
          aria-label={t("controls.next")}
          disabled={!ready || page >= total}
          onClick={() => {
            if (viewerRef.current)
              viewerRef.current.currentPageNumber = page + 1;
          }}
        />
        <Button
          icon={SvgMinus}
          size="sm"
          prominence="tertiary"
          aria-label={t("controls.zoomOut")}
          disabled={!ready}
          onClick={() => viewerRef.current?.decreaseScale()}
        />
        <Button
          icon={SvgPlus}
          size="sm"
          prominence="tertiary"
          aria-label={t("controls.zoomIn")}
          disabled={!ready}
          onClick={() => viewerRef.current?.increaseScale()}
        />
        <Button
          size="sm"
          prominence="tertiary"
          disabled={!ready}
          onClick={() => {
            if (viewerRef.current)
              viewerRef.current.currentScaleValue = "page-width";
          }}
        >
          {t("controls.fitWidth")}
        </Button>
      </div>
      <div className="relative flex-1 min-h-0">
        <div
          ref={containerRef}
          role="region"
          aria-label={filePath.split("/").pop() || t("frame.title")}
          className="absolute inset-0 overflow-auto"
        >
          <div ref={pagesRef} className="pdfViewer" />
        </div>
        {!ready && <PdfLoading />}
      </div>
    </div>
  );
}

function PdfError() {
  const t = useTranslations("craft.pdfPreview");

  return (
    <Section
      height="full"
      alignItems="center"
      justifyContent="center"
      padding={8}
    >
      <SvgFileText size={48} className="stroke-text-02" />
      <Text font="heading-h3" color="text-03">
        {t("error.title")}
      </Text>
      <div className="text-center max-w-md">
        <Text font="secondary-body" color="text-02">
          {t("error.description")}
        </Text>
      </div>
    </Section>
  );
}

function PdfLoading() {
  const t = useTranslations("craft.pdfPreview");
  return (
    <Section
      height="full"
      alignItems="center"
      justifyContent="center"
      padding={8}
    >
      <Text font="secondary-body" color="text-03">
        {t("loading.label")}
      </Text>
    </Section>
  );
}
