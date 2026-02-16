"use client";

import { useEffect } from "react";
import useSWR from "swr";
import { fetchFileContent } from "@/app/craft/services/apiServices";
import Text from "@/refresh-components/texts/Text";
import { SvgFileText } from "@opal/icons";
import { Section } from "@/layouts/general-layouts";
import ImagePreview from "@/app/craft/components/output-panel/ImagePreview";
import MarkdownFilePreview, {
  type FileRendererProps,
} from "@/app/craft/components/output-panel/MarkdownFilePreview";
import PptxPreview from "@/app/craft/components/output-panel/PptxPreview";
import PdfPreview from "@/app/craft/components/output-panel/PdfPreview";

// ── Preview registry ─────────────────────────────────────────────────────
// Unified registry for all file preview types. First match wins.
//
// "standalone" — binary formats that handle their own data fetching.
// "content"    — text-based formats that receive already-fetched content.

interface StandaloneEntry {
  type: "standalone";
  matches: (filePath: string) => boolean;
  component: React.FC<{
    sessionId: string;
    filePath: string;
    refreshKey?: number;
  }>;
}

interface ContentEntry {
  type: "content";
  matches: (filePath: string, mimeType: string, isImage: boolean) => boolean;
  component: React.FC<FileRendererProps>;
}

type PreviewEntry = StandaloneEntry | ContentEntry;

function ImageRendererWrapper({ content, fileName }: FileRendererProps) {
  return <ImagePreview src={content} fileName={fileName} />;
}

const PREVIEW_REGISTRY: PreviewEntry[] = [
  {
    type: "standalone",
    matches: (path) => /\.pptx$/i.test(path),
    component: PptxPreview,
  },
  {
    type: "standalone",
    matches: (path) => /\.pdf$/i.test(path),
    component: PdfPreview,
  },
  {
    type: "content",
    matches: (_, __, isImage) => isImage,
    component: ImageRendererWrapper,
  },
  {
    type: "content",
    matches: (path) => /\.md$/i.test(path),
    component: MarkdownFilePreview,
  },
];

function findStandalonePreview(filePath: string): StandaloneEntry | undefined {
  return PREVIEW_REGISTRY.find(
    (e): e is StandaloneEntry => e.type === "standalone" && e.matches(filePath)
  );
}

function findContentPreview(
  filePath: string,
  mimeType: string,
  isImage: boolean
): ContentEntry | undefined {
  return PREVIEW_REGISTRY.find(
    (e): e is ContentEntry =>
      e.type === "content" && e.matches(filePath, mimeType, isImage)
  );
}

// ── Public components ────────────────────────────────────────────────────

interface FilePreviewContentProps {
  sessionId: string;
  filePath: string;
  /** Changing this value forces the preview to reload its data */
  refreshKey?: number;
}

/**
 * FilePreviewContent — full-height file preview for the main output panel.
 * Routes to the appropriate preview component based on file type.
 */
export function FilePreviewContent({
  sessionId,
  filePath,
  refreshKey,
}: FilePreviewContentProps) {
  const standalone = findStandalonePreview(filePath);
  if (standalone) {
    const Comp = standalone.component;
    return (
      <Comp sessionId={sessionId} filePath={filePath} refreshKey={refreshKey} />
    );
  }

  return (
    <FetchedFilePreview
      sessionId={sessionId}
      filePath={filePath}
      fullHeight
      refreshKey={refreshKey}
    />
  );
}

/**
 * InlineFilePreview — compact file preview for pre-provisioned mode.
 * Same routing logic, without full-height layout.
 */
export function InlineFilePreview({
  sessionId,
  filePath,
}: FilePreviewContentProps) {
  const standalone = findStandalonePreview(filePath);
  if (standalone) {
    const Comp = standalone.component;
    return <Comp sessionId={sessionId} filePath={filePath} />;
  }

  return <FetchedFilePreview sessionId={sessionId} filePath={filePath} />;
}

// ── FetchedFilePreview (inner) ───────────────────────────────────────────

interface FetchedFilePreviewProps {
  sessionId: string;
  filePath: string;
  fullHeight?: boolean;
  refreshKey?: number;
}

/**
 * Fetches file content via SWR, then delegates to the first matching
 * "content" entry in the registry (or falls back to raw monospace text).
 */
function FetchedFilePreview({
  sessionId,
  filePath,
  fullHeight,
  refreshKey,
}: FetchedFilePreviewProps) {
  const { data, error, isLoading, mutate } = useSWR(
    `/api/build/sessions/${sessionId}/artifacts/${filePath}`,
    () => fetchFileContent(sessionId, filePath),
    {
      revalidateOnFocus: false,
      dedupingInterval: 5000,
    }
  );

  // Re-fetch when refreshKey changes
  useEffect(() => {
    if (refreshKey && refreshKey > 0) {
      mutate();
    }
  }, [refreshKey, mutate]);

  if (isLoading) {
    if (fullHeight) {
      return (
        <Section
          height="full"
          alignItems="center"
          justifyContent="center"
          padding={2}
        >
          <Text secondaryBody text03>
            Loading file...
          </Text>
        </Section>
      );
    }
    return (
      <div className="p-4">
        <Text secondaryBody text03>
          Loading file...
        </Text>
      </div>
    );
  }

  if (error) {
    if (fullHeight) {
      return (
        <Section
          height="full"
          alignItems="center"
          justifyContent="center"
          padding={2}
        >
          <SvgFileText size={48} className="stroke-text-02" />
          <Text headingH3 text03>
            Error loading file
          </Text>
          <Text secondaryBody text02>
            {error.message}
          </Text>
        </Section>
      );
    }
    return (
      <div className="p-4">
        <Text secondaryBody text02>
          Error: {error.message}
        </Text>
      </div>
    );
  }

  if (!data) {
    if (fullHeight) {
      return (
        <Section
          height="full"
          alignItems="center"
          justifyContent="center"
          padding={2}
        >
          <Text secondaryBody text03>
            No content
          </Text>
        </Section>
      );
    }
    return (
      <div className="p-4">
        <Text secondaryBody text03>
          No content
        </Text>
      </div>
    );
  }

  if (data.error) {
    if (fullHeight) {
      return (
        <Section
          height="full"
          alignItems="center"
          justifyContent="center"
          padding={2}
        >
          <SvgFileText size={48} className="stroke-text-02" />
          <Text headingH3 text03>
            Cannot preview file
          </Text>
          <Text secondaryBody text02 className="text-center max-w-md">
            {data.error}
          </Text>
        </Section>
      );
    }
    return (
      <div className="p-4">
        <Text secondaryBody text02 className="text-center">
          {data.error}
        </Text>
      </div>
    );
  }

  // Match against content-based renderers
  const fileName = filePath.split("/").pop() || filePath;
  const mimeType = data.mimeType ?? "text/plain";
  const isImage = !!data.isImage;

  const contentPreview = findContentPreview(filePath, mimeType, isImage);
  if (contentPreview) {
    const Comp = contentPreview.component;
    return (
      <Comp
        content={data.content}
        fileName={fileName}
        filePath={filePath}
        mimeType={mimeType}
        isImage={isImage}
      />
    );
  }

  // Default fallback: raw text
  if (fullHeight) {
    return (
      <div className="h-full flex flex-col">
        <div className="flex-1 overflow-auto p-4">
          <pre className="font-mono text-sm text-text-04 whitespace-pre-wrap break-words">
            {data.content}
          </pre>
        </div>
      </div>
    );
  }

  return (
    <div className="p-4">
      <pre className="font-mono text-sm text-text-04 whitespace-pre-wrap break-words">
        {data.content}
      </pre>
    </div>
  );
}
