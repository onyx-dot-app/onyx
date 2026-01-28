"use client";

import useSWR from "swr";
import { fetchFileContent } from "@/app/craft/services/apiServices";
import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import { SvgFileText } from "@opal/icons";
import { Section } from "@/layouts/general-layouts";
import ImagePreview from "@/app/craft/components/output-panel/ImagePreview";
import MarkdownFilePreview, {
  type FileRendererProps,
} from "@/app/craft/components/output-panel/MarkdownFilePreview";

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
 * Fetches content via SWR and displays loading/error/content states
 */
export function FilePreviewContent({
  sessionId,
  filePath,
}: FilePreviewContentProps) {
  const { data, error, isLoading } = useSWR(
    `/api/build/sessions/${sessionId}/artifacts/${filePath}`,
    () => fetchFileContent(sessionId, filePath),
    {
      revalidateOnFocus: false,
      dedupingInterval: 5000,
    }
  );

  if (isLoading) {
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
          Error loading file
        </Text>
        <Text secondaryBody text02>
          {error.message}
        </Text>
      </Section>
    );
  }

  if (!data) {
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

  // Display error if image is too large or had issues
  if (data.error) {
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
  const { data, error, isLoading } = useSWR(
    `/api/build/sessions/${sessionId}/artifacts/${filePath}`,
    () => fetchFileContent(sessionId, filePath),
    {
      revalidateOnFocus: false,
      dedupingInterval: 5000,
    }
  );

  if (isLoading) {
    return (
      <div className="p-4">
        <Text secondaryBody text03>
          Loading file...
        </Text>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4">
        <Text secondaryBody text02>
          Error: {error.message}
        </Text>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="p-4">
        <Text secondaryBody text03>
          No content
        </Text>
      </div>
    );
  }

  // Display error if image is too large or had issues
  if (data.error) {
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
  return (
    <div className="p-4">
      <pre className="font-mono text-sm text-text-04 whitespace-pre-wrap break-words">
        {data.content}
      </pre>
    </div>
  );
}
