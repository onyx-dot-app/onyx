"use client";

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

// ── File renderer registry ───────────────────────────────────────────────
// Ordered by priority — first match wins.
// To add a new preview type, add an entry here + create a component.
interface FileRenderer {
  canRender: (filePath: string, mimeType: string, isImage: boolean) => boolean;
  component: React.FC<FileRendererProps>;
}

function ImageRendererWrapper({ content, fileName }: FileRendererProps) {
  return <ImagePreview src={content} fileName={fileName} />;
}

const FILE_RENDERERS: FileRenderer[] = [
  {
    canRender: (_, __, isImage) => isImage,
    component: ImageRendererWrapper,
  },
  {
    canRender: (path) => /\.md$/i.test(path),
    component: MarkdownFilePreview,
  },
];

// ── FilePreviewContent ───────────────────────────────────────────────────

interface FilePreviewContentProps {
  sessionId: string;
  filePath: string;
}

/**
 * FilePreviewContent - Displays file content in a scrollable monospace view
 * Fetches content via SWR and displays loading/error/content states.
 * PPTX files are handled by a dedicated preview component.
 */
export function FilePreviewContent({
  sessionId,
  filePath,
}: FilePreviewContentProps) {
  if (/\.pptx$/i.test(filePath)) {
    return <PptxPreview sessionId={sessionId} filePath={filePath} />;
  }

  return (
    <GenericFilePreview sessionId={sessionId} filePath={filePath} fullHeight />
  );
}

// ── InlineFilePreview ────────────────────────────────────────────────────

/**
 * InlineFilePreview - Simple file preview for pre-provisioned mode
 * Same as FilePreviewContent but without the full height wrapper
 */
export function InlineFilePreview({
  sessionId,
  filePath,
}: {
  sessionId: string;
  filePath: string;
}) {
  if (/\.pptx$/i.test(filePath)) {
    return <PptxPreview sessionId={sessionId} filePath={filePath} />;
  }

  return <GenericFilePreview sessionId={sessionId} filePath={filePath} />;
}

// ── GenericFilePreview (inner) ───────────────────────────────────────────

interface GenericFilePreviewProps {
  sessionId: string;
  filePath: string;
  fullHeight?: boolean;
}

/**
 * Inner component that uses SWR to fetch and render non-PPTX files.
 * Extracted to keep hooks unconditional within this component.
 */
function GenericFilePreview({
  sessionId,
  filePath,
  fullHeight,
}: GenericFilePreviewProps) {
  const { data, error, isLoading } = useSWR(
    `/api/build/sessions/${sessionId}/artifacts/${filePath}`,
    () => fetchFileContent(sessionId, filePath),
    {
      revalidateOnFocus: false,
      dedupingInterval: 5000,
    }
  );

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

  // Use renderer registry — first match wins
  const fileName = filePath.split("/").pop() || filePath;
  const rendererProps: FileRendererProps = {
    content: data.content,
    fileName,
    filePath,
    mimeType: data.mimeType ?? "text/plain",
    isImage: !!data.isImage,
  };

  const renderer = FILE_RENDERERS.find((r) =>
    r.canRender(filePath, rendererProps.mimeType, rendererProps.isImage)
  );

  if (renderer) {
    const Comp = renderer.component;
    return <Comp {...rendererProps} />;
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
