"use client";

import { IconLoader } from "@opal/loaders";
import { useState, useEffect, useRef } from "react";
import { useTranslations } from "next-intl";
import { renderDocx } from "@/lib/docx/renderDocx";
import ScrollIndicatorDiv from "@/refresh-components/ScrollIndicatorDiv";
import { Text } from "@opal/components";

import { Section } from "@opal/layouts";
import { PreviewContext } from "@/sections/modals/PreviewModal/interfaces";
import { PreviewVariant } from "@/sections/modals/PreviewModal/interfaces";
import { CopyButton } from "@opal/components";
import { DownloadButton } from "@/sections/modals/PreviewModal/variants/shared";

const DOCX_MIMES = [
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "application/msword",
];

function isLegacyDoc(fileName: string): boolean {
  const lower = fileName.toLowerCase();
  return lower.endsWith(".doc") && !lower.endsWith(".docx");
}

interface DocxLoadResult {
  plainText: string;
  wordCount: number;
}

interface DocxPreviewProps {
  fileUrl: string;
  onLoad: (result: DocxLoadResult) => void;
}

function DocxPreview({ fileUrl, onLoad }: DocxPreviewProps) {
  const t = useTranslations("chat.modals.preview");
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  const onLoadRef = useRef(onLoad);

  useEffect(() => {
    onLoadRef.current = onLoad;
  }, [onLoad]);

  useEffect(() => {
    let cancelled = false;
    async function loadDocument() {
      setIsLoading(true);
      setError(null);
      try {
        const response = await fetch(fileUrl);
        if (!response.ok) {
          throw new Error(`Failed to fetch document: ${response.status}`);
        }
        const buffer = await response.arrayBuffer();

        const rendered = await renderDocx(buffer);
        if (cancelled) return;
        const host = bodyRef.current;
        if (!host) return;
        const root = host.shadowRoot ?? host.attachShadow({ mode: "open" });
        root.replaceChildren(rendered.styles, rendered.body);

        // Extract plain text from the rendered DOM
        const text = rendered.body.innerText ?? "";
        const words = text
          .split(/\s+/)
          .filter((w: string) => w.length > 0).length;

        onLoadRef.current({ plainText: text, wordCount: words });
      } catch {
        if (!cancelled) setError(t("docx.loadError.message"));
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    }
    void loadDocument();
    return () => {
      cancelled = true;
    };
  }, [fileUrl, t]);

  if (error) {
    return (
      <Section justifyContent="center" alignItems="center" padding={6}>
        <Text color="text-03" font="main-ui-body">
          {error}
        </Text>
      </Section>
    );
  }

  return (
    <ScrollIndicatorDiv
      className="flex-1 min-h-0 bg-background-tint-00"
      variant="shadow"
    >
      {isLoading && (
        <Section>
          <IconLoader className="h-8 w-8" />
        </Section>
      )}
      {/* Body container where docx-preview renders the document */}
      <div ref={bodyRef} className="docx-host px-32 py-16" />
    </ScrollIndicatorDiv>
  );
}

// Store parsed result outside the variant so footer can access it
let lastDocxResult: DocxLoadResult | null = null;

export const docxVariant: PreviewVariant = {
  matches: (name, mime) => {
    if (DOCX_MIMES.some((m) => mime === m)) return true;
    const lower = (name || "").toLowerCase();
    return lower.endsWith(".docx") || lower.endsWith(".doc");
  },
  width: "full",
  height: "full",
  needsTextContent: false,
  codeBackground: false,
  headerDescription: (ctx: PreviewContext) => {
    if (lastDocxResult) {
      return ctx.t("docx.headerDescription", {
        count: lastDocxResult.wordCount,
      });
    }
    return ctx.t("docx.headerDescriptionFallback");
  },

  renderContent: (ctx: PreviewContext) => {
    if (isLegacyDoc(ctx.fileName)) {
      lastDocxResult = null;
      return (
        <Section justifyContent="center" alignItems="center" padding={6}>
          <Text color="text-03" font="main-ui-body">
            {ctx.t("docx.legacyDocMessage")}
          </Text>
        </Section>
      );
    }
    return (
      <DocxPreview
        fileUrl={ctx.fileUrl}
        onLoad={(result) => {
          lastDocxResult = result;
        }}
      />
    );
  },

  renderFooterLeft: () => null,
  renderFooterRight: (ctx: PreviewContext) => (
    <Section flexDirection="row" width="fit">
      {lastDocxResult && (
        <CopyButton
          size="sm"
          tooltip={ctx.t("copyButton.tooltip")}
          getCopyText={() => lastDocxResult?.plainText ?? ""}
        />
      )}
      <DownloadButton fileUrl={ctx.fileUrl} fileName={ctx.fileName} />
    </Section>
  ),
};
