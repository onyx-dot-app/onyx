"use client";

import { useState, useEffect, useRef } from "react";
import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import { SvgFileText } from "@opal/icons";
import { Section } from "@/layouts/general-layouts";
import { getArtifactUrl } from "@/lib/build/client";

interface PdfPreviewProps {
  sessionId: string;
  filePath: string;
  refreshKey?: number;
}

/**
 * PdfPreview - Renders PDF files using the browser's built-in PDF viewer.
 * Fetches the PDF as a blob and creates an object URL so the iframe renders
 * it inline (the backend serves artifacts with Content-Disposition: attachment,
 * which would otherwise force a download).
 */
export default function PdfPreview({
  sessionId,
  filePath,
  refreshKey,
}: PdfPreviewProps) {
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const blobUrlRef = useRef<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();

    // Revoke the previous blob URL before starting a new fetch
    if (blobUrlRef.current) {
      URL.revokeObjectURL(blobUrlRef.current);
      blobUrlRef.current = null;
    }
    setBlobUrl(null);
    setLoading(true);
    setError(false);

    const encodedPath = filePath
      .split("/")
      .map((segment) => encodeURIComponent(segment))
      .join("/");
    const artifactUrl = getArtifactUrl(sessionId, encodedPath);

    fetch(artifactUrl, { signal: controller.signal })
      .then((res) => {
        if (!res.ok) throw new Error(`Failed to fetch PDF: ${res.status}`);
        return res.blob();
      })
      .then((blob) => {
        const url = URL.createObjectURL(blob);
        blobUrlRef.current = url;
        setBlobUrl(url);
        setLoading(false);
      })
      .catch((err) => {
        if (err instanceof DOMException && err.name === "AbortError") return;
        setError(true);
        setLoading(false);
      });

    return () => {
      controller.abort();
      if (blobUrlRef.current) {
        URL.revokeObjectURL(blobUrlRef.current);
        blobUrlRef.current = null;
      }
    };
  }, [sessionId, filePath, refreshKey]);

  if (error) {
    return (
      <Section
        height="full"
        alignItems="center"
        justifyContent="center"
        padding={2}
      >
        <SvgFileText size={48} className="stroke-text-02" />
        <Text headingH3 text03>
          Cannot preview PDF
        </Text>
        <Text secondaryBody text02 className="text-center max-w-md">
          The PDF file could not be loaded.
        </Text>
      </Section>
    );
  }

  if (loading || !blobUrl) {
    return (
      <Section
        height="full"
        alignItems="center"
        justifyContent="center"
        padding={2}
      >
        <Text secondaryBody text03>
          Loading PDF...
        </Text>
      </Section>
    );
  }

  return (
    <iframe
      src={blobUrl}
      title={filePath.split("/").pop() || "PDF Preview"}
      className={cn("w-full h-full border-none")}
    />
  );
}
