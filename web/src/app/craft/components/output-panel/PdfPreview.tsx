"use client";

import { useState, useEffect, useRef } from "react";
import type { PDFDocumentLoadingTask, PDFDocumentProxy } from "pdfjs-dist";
import type {
  EventBus,
  PDFLinkService,
  PDFViewer,
} from "pdfjs-dist/web/pdf_viewer.mjs";
import "pdfjs-dist/web/pdf_viewer.css";
import useSWR from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import { useTranslations } from "next-intl";
import { Button, InputPasswordTypeIn, Text } from "@opal/components";
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
  } = useSWR<Blob, Error>(
    [
      SWR_KEYS.buildSessionArtifactFile(sessionId, filePath),
      "pdf",
      revision,
      refreshKey ?? 0,
    ],
    async () => {
      const response: Response = await fetch(
        buildArtifactUrl(sessionId, filePath),
        {
          cache: "no-store",
        }
      );
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

interface PdfDocumentProps {
  blob: Blob;
  filePath: string;
}

interface PdfPasswordRequest {
  submit: (password: string) => void;
  cancel: () => void;
  incorrect: boolean;
}

function PdfDocument({ blob, filePath }: PdfDocumentProps) {
  const t = useTranslations("craft.pdfPreview");
  const containerRef = useRef<HTMLDivElement>(null);
  const pagesRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<PDFViewer | null>(null);
  const [ready, setReady] = useState<boolean>(false);
  const [error, setError] = useState<boolean>(false);
  const [page, setPage] = useState<number>(1);
  const [total, setTotal] = useState<number>(0);

  const [passwordRequest, setPasswordRequest] =
    useState<PdfPasswordRequest | null>(null);

  useEffect(() => {
    const container: HTMLDivElement | null = containerRef.current;
    const pages: HTMLDivElement | null = pagesRef.current;
    if (!container || !pages) return;
    const controller: AbortController = new AbortController();
    let dispose: (() => void) | undefined;
    setReady(false);
    setError(false);
    setPasswordRequest(null);

    function disposeDocument(): void {
      controller.abort();
      const cleanup: (() => void) | undefined = dispose;
      dispose = undefined;
      cleanup?.();
    }

    function fail(): void {
      if (controller.signal.aborted) return;
      disposeDocument();
      setPasswordRequest(null);
      setError(true);
    }

    async function load(): Promise<void> {
      if (!container || !pages) return;
      const pdfjs: typeof import("pdfjs-dist") = await import("pdfjs-dist");
      const viewerModule: typeof import("pdfjs-dist/web/pdf_viewer.mjs") =
        await import("pdfjs-dist/web/pdf_viewer.mjs");
      const bytes: ArrayBuffer = await blob.arrayBuffer();
      if (controller.signal.aborted) return;
      const assets: string = `/pdfjs/${pdfjs.version}`;
      pdfjs.GlobalWorkerOptions.workerSrc = `${assets}/pdf.worker.min.mjs`;
      const eventBus: EventBus = new viewerModule.EventBus();
      const linkService: PDFLinkService = new viewerModule.PDFLinkService({
        eventBus,
        externalLinkTarget: viewerModule.LinkTarget.BLANK,
        externalLinkRel: "noopener noreferrer",
      });
      // PDF.js accepts abortSignal, but its published options type omits it.
      const viewerOptions: ConstructorParameters<typeof PDFViewer>[0] & {
        abortSignal: AbortSignal;
      } = {
        container,
        viewer: pages,
        eventBus,
        linkService,
        abortSignal: controller.signal,
        annotationMode: pdfjs.AnnotationMode.ENABLE,
        imageResourcesPath: `${assets}/web/images/`,
      };
      const viewer: PDFViewer = new viewerModule.PDFViewer(viewerOptions);
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
          if (renderError) fail();
        }
      );
      const task: PDFDocumentLoadingTask = pdfjs.getDocument({
        // PDF.js transfers this buffer to its worker. SWR retains the original Blob.
        data: bytes,
        cMapUrl: `${assets}/cmaps/`,
        cMapPacked: true,
        standardFontDataUrl: `${assets}/standard_fonts/`,
        wasmUrl: `${assets}/wasm/`,
        iccUrl: `${assets}/iccs/`,
      });
      task.onPassword = (
        submit: (password: string) => void,
        reason: number
      ): void => {
        if (controller.signal.aborted) return;
        setPasswordRequest({
          submit,
          cancel: fail,
          incorrect: reason === pdfjs.PasswordResponses.INCORRECT_PASSWORD,
        });
      };
      let previousWidth: number = container.clientWidth;
      const resizeObserver: ResizeObserver = new ResizeObserver(() => {
        const width: number = container.clientWidth;
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
      const document: PDFDocumentProxy = await task.promise;
      if (controller.signal.aborted) return;
      setTotal(document.numPages);
      linkService.setDocument(document);
      viewer.setDocument(document);
    }
    void load().catch(fail);
    return disposeDocument;
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
        {passwordRequest ? (
          <div className="absolute inset-0 z-10 background-neutral-01">
            <PdfPasswordPrompt
              incorrect={passwordRequest.incorrect}
              onSubmit={(password: string) => {
                setPasswordRequest(null);
                passwordRequest.submit(password);
              }}
              onCancel={passwordRequest.cancel}
            />
          </div>
        ) : (
          !ready && <PdfLoading />
        )}
      </div>
    </div>
  );
}

interface PdfPasswordPromptProps {
  incorrect: boolean;
  onSubmit: (password: string) => void;
  onCancel: () => void;
}

function PdfPasswordPrompt({
  incorrect,
  onSubmit,
  onCancel,
}: PdfPasswordPromptProps) {
  const t = useTranslations("craft.pdfPreview");
  const [password, setPassword] = useState<string>("");

  return (
    <Section
      height="full"
      alignItems="center"
      justifyContent="center"
      padding={8}
    >
      <form
        className="flex flex-col gap-3 w-full max-w-sm"
        onSubmit={(event) => {
          event.preventDefault();
          if (password) {
            onSubmit(password);
            setPassword("");
          }
        }}
      >
        <Text font="heading-h3" color="text-03">
          {t("password.title")}
        </Text>
        <Text font="secondary-body" color="text-02">
          {t("password.description")}
        </Text>
        {incorrect && (
          <div role="alert">
            <Text font="secondary-body" color="text-02">
              {t("password.incorrect")}
            </Text>
          </div>
        )}
        <InputPasswordTypeIn
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          aria-label={t("password.label")}
          error={incorrect}
          mask="native"
        />
        <div className="flex justify-end gap-2">
          <Button prominence="secondary" onClick={onCancel}>
            {t("password.cancel")}
          </Button>
          <Button type="submit" disabled={!password}>
            {t("password.submit")}
          </Button>
        </div>
      </form>
    </Section>
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
