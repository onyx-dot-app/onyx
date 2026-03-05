"use client";

import { useState, useEffect, useRef } from "react";
import { renderAsync } from "docx-preview";
import ScrollIndicatorDiv from "@/refresh-components/ScrollIndicatorDiv";
import Text from "@/refresh-components/texts/Text";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import { Section } from "@/layouts/general-layouts";
import { PreviewContext } from "@/sections/modals/PreviewModal/interfaces";
import { PreviewVariant } from "@/sections/modals/PreviewModal/interfaces";
import {
  CopyButton,
  DownloadButton,
} from "@/sections/modals/PreviewModal/variants/shared";

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
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  const styleRef = useRef<HTMLDivElement>(null);
  const onLoadRef = useRef(onLoad);
  onLoadRef.current = onLoad;

  useEffect(() => {
    async function loadDocument() {
      try {
        const response = await fetch(fileUrl);
        if (!response.ok) {
          throw new Error(`Failed to fetch document: ${response.status}`);
        }
        const buffer = await response.arrayBuffer();

        // Render the DOCX with full layout fidelity
        if (bodyRef.current && styleRef.current) {
          bodyRef.current.innerHTML = "";
          styleRef.current.innerHTML = "";

          await renderAsync(buffer, bodyRef.current, styleRef.current, {
            className: "docx",
            inWrapper: false,
            ignoreWidth: false,
            ignoreHeight: false,
            ignoreFonts: false,
            breakPages: true,
            useBase64URL: true,
            renderHeaders: true,
            renderFooters: true,
            renderFootnotes: true,
            renderEndnotes: true,
          });
        }

        // Extract plain text from the rendered DOM
        const text = bodyRef.current?.innerText ?? "";
        const words = text
          .split(/\s+/)
          .filter((w: string) => w.length > 0).length;

        onLoadRef.current({ plainText: text, wordCount: words });
      } catch {
        setError(
          "Could not preview this document. Download the file to view it."
        );
      } finally {
        setIsLoading(false);
      }
    }
    loadDocument();
  }, [fileUrl]);

  if (error) {
    return (
      <Section justifyContent="center" alignItems="center" padding={1.5}>
        <Text text03 mainUiBody>
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
          <SimpleLoader className="h-8 w-8" />
        </Section>
      )}
      {/* Style container for docx-preview generated styles */}
      <div ref={styleRef} />
      {/* Body container where docx-preview renders the document */}
      <div ref={bodyRef} className="docx-host px-32 pb-16" />
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
  width: "lg",
  height: "full",
  needsTextContent: false,
  headerDescription: () => {
    if (lastDocxResult) {
      const count = lastDocxResult.wordCount;
      return `Word Document • ${count.toLocaleString()} ${
        count === 1 ? "word" : "words"
      }`;
    }
    return "Word Document";
  },

  renderContent: (ctx: PreviewContext) => {
    if (isLegacyDoc(ctx.fileName)) {
      return (
        <Section justifyContent="center" alignItems="center" padding={1.5}>
          <Text text03 mainUiBody>
            Legacy .doc format cannot be previewed. Download the file to view
            it.
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
        <CopyButton getText={() => lastDocxResult?.plainText ?? ""} />
      )}
      <DownloadButton fileUrl={ctx.fileUrl} fileName={ctx.fileName} />
    </Section>
  ),
};
