"use client";

import type { RichStr } from "@opal/types";
import { memo, useMemo, useRef, type ReactNode } from "react";
import useSWR from "swr";
import { useInView } from "motion/react";
import { useTranslations } from "next-intl";
import { Text } from "@opal/components";
import { CardGrid, Section } from "@opal/layouts";
import { cn } from "@opal/utils";
import type { PublishedFile } from "@/app/app/services/streamingModels";
import { buildImgUrl } from "@/app/app/components/files/images/utils";
import { getFileIcon } from "@/lib/utils";
import { downloadFile } from "@/lib/download";
import {
  artifactKey,
  filesSharingALabel,
  publishedFileLabel,
  publishedFilePath,
} from "@/lib/chat/publishedFiles";
import { WorkspaceHome } from "@/sections/output-panel/WorkspaceHome";
import {
  OutputImageThumbnail,
  OutputTileFrame,
} from "@/sections/output-panel/OutputTile";
import { useChatFilePreview } from "@/lib/filePreview/hooks";
import { resolveFilePreviewFormat } from "@/lib/filePreview/format";
import { fetchChatFile } from "@/lib/chat/svc";
import { loadChatFilePreview } from "@/lib/filePreview/loadChatFilePreview";
import { renderDocumentThumbnail } from "@/lib/filePreview/documentThumbnail";
import { SWR_KEYS } from "@/lib/swr-keys";
import { MarkdownFilePreview } from "@/sections/file-preview/MarkdownFilePreview";
import {
  FilePreviewBody,
  FilePreviewScope,
} from "@/sections/file-preview/FilePreview";

const IMAGE_FILE = /\.(png|jpe?g|gif|webp|svg|avif)$/i;
// A text tile shows the start of its file, as Craft's: files up to this size
// load for it
const TILE_TEXT_MAX_BYTES = 256 * 1024;
const TILE_TEXT_CHARACTERS = 4000;
// A chat file never changes, so a tile's preview loads once per session
const TILE_PREVIEW_SWR_OPTIONS = {
  revalidateOnFocus: false,
  revalidateOnReconnect: false,
  revalidateIfStale: false,
  shouldRetryOnError: false,
};

interface TextTilePreviewProps {
  file: PublishedFile;
  markdown: boolean;
  // Shown when the text does not load
  fallback: ReactNode;
}

/**
 * The start of a text or markdown file as its tile's preview, scaled down as
 * Craft's. It loads once the tile nears the view.
 */
function TextTilePreview({ file, markdown, fallback }: TextTilePreviewProps) {
  const ref = useRef<HTMLDivElement>(null);
  const near = useInView(ref, { margin: "200px", once: true });
  const { data, error } = useSWR(
    near ? SWR_KEYS.chatFileTileText(file.file_id) : null,
    async () => {
      const response = await fetchChatFile(file.file_id);
      return (await response.text()).slice(0, TILE_TEXT_CHARACTERS);
    },
    TILE_PREVIEW_SWR_OPTIONS
  );
  return (
    <div
      ref={ref}
      inert
      className={cn(
        "relative h-full w-full overflow-hidden text-start pointer-events-none",
        // The text sits on a page; the icon on the tile's own background
        data !== undefined && "bg-background-neutral-00"
      )}
    >
      {data !== undefined ? (
        <div className="absolute start-0 top-0 w-[222%] origin-top-left scale-45 p-5 rtl:origin-top-right">
          {markdown ? (
            <MarkdownFilePreview text={data} thumbnail />
          ) : (
            <div className="whitespace-pre-wrap">
              <Text
                as="p"
                font="secondary-mono"
                color="text-04"
                wordWrap="wrap-anywhere"
              >
                {data}
              </Text>
            </div>
          )}
        </div>
      ) : error ? (
        <Section>{fallback}</Section>
      ) : (
        <div className="h-full w-full bg-background-neutral-02" />
      )}
    </div>
  );
}

interface DocumentTilePreviewProps {
  file: PublishedFile;
  // Shown while the thumbnail loads, and when it does not
  fallback: ReactNode;
}

/**
 * The first page of a PDF, or the first slide of a deck, as its tile's
 * preview, as Craft's. It loads once the tile nears the view, through the
 * file preview's loader and limits. The image is kept for the session, so the
 * tile does not draw it again when it mounts again or resizes.
 */
function DocumentTilePreview({ file, fallback }: DocumentTilePreviewProps) {
  const ref = useRef<HTMLDivElement>(null);
  const near = useInView(ref, { margin: "200px", once: true });
  const { data } = useSWR(
    near ? SWR_KEYS.chatFileTileThumbnail(file.file_id) : null,
    async () =>
      renderDocumentThumbnail(
        await loadChatFilePreview(file.file_id, file.name)
      ),
    TILE_PREVIEW_SWR_OPTIONS
  );
  return (
    <div ref={ref} className="h-full w-full">
      {data !== undefined ? (
        <OutputImageThumbnail src={data} fallback={fallback} />
      ) : (
        <Section>{fallback}</Section>
      )}
    </div>
  );
}

interface PublishedFilesGridProps {
  // The newest version of each artifact, newest artifact first
  files: PublishedFile[];
  // Files to mark with Craft's new-file marker
  unseenFileIds: string[];
  // Shown in place of the tiles when `files` is empty
  emptyLabel: string | RichStr;
  onOpen: (file: PublishedFile) => void;
}

/**
 * The Files tab of the chat's right panel: Craft's output tiles for the files
 * the model published. Files of one shown name also show their path.
 */
export const PublishedFilesGrid = memo(function PublishedFilesGrid({
  files,
  unseenFileIds,
  emptyLabel,
  onOpen,
}: PublishedFilesGridProps) {
  const t = useTranslations("chat.rightPanel");
  const sharingALabel = useMemo(() => filesSharingALabel(files), [files]);

  return (
    <WorkspaceHome title={t("filesTab.description")} wide>
      {files.length === 0 && (
        <div role="status" className="text-center">
          <Text as="p" font="main-ui-muted" color="text-03">
            {emptyLabel}
          </Text>
        </div>
      )}
      <CardGrid columns="two-to-three">
        {files.map((file) => {
          const name = sharingALabel.has(file.file_id)
            ? publishedFilePath(file)
            : publishedFileLabel(file);
          const FileIcon = getFileIcon(file.name);
          const { kind } = resolveFilePreviewFormat(file.name, file.mime_type);
          const textKind = kind === "markdown" || kind === "code" ? kind : null;
          const icon = (
            <FileIcon
              size={32}
              className="size-8 stroke-text-03 @[40rem]:size-10 [&_*]:stroke-1"
            />
          );
          return (
            <div
              key={artifactKey(file)}
              data-published-file={artifactKey(file)}
            >
              <OutputTileFrame
                label={t("filesTab.tile.ariaLabel", { name })}
                name={name}
                isUnseen={unseenFileIds.includes(file.file_id)}
                onOpen={() => onOpen(file)}
                onDownload={() =>
                  downloadFile(file.name, { url: buildImgUrl(file.file_id) })
                }
                preview={
                  IMAGE_FILE.test(file.name) ? (
                    <OutputImageThumbnail
                      src={buildImgUrl(file.file_id)}
                      fallback={icon}
                      lazy
                    />
                  ) : kind === "pdf" || kind === "pptx" ? (
                    <DocumentTilePreview file={file} fallback={icon} />
                  ) : textKind !== null && file.size <= TILE_TEXT_MAX_BYTES ? (
                    <TextTilePreview
                      file={file}
                      markdown={textKind === "markdown"}
                      fallback={icon}
                    />
                  ) : (
                    icon
                  )
                }
              />
            </div>
          );
        })}
      </CardGrid>
    </WorkspaceHome>
  );
});

interface PublishedFilePreviewProps {
  file: PublishedFile;
}

function PublishedFilePreviewContent({ file }: PublishedFilePreviewProps) {
  const t = useTranslations("chat.publishedFiles");
  const preview = useChatFilePreview(file.file_id, file.name);

  return (
    <Section
      tabIndex={-1}
      role="region"
      aria-label={t("panel.preview.ariaLabel", {
        name: publishedFileLabel(file),
      })}
      data-published-preview={file.file_id}
      gap={0}
      justifyContent="start"
      alignItems="stretch"
      className="outline-none"
    >
      <FilePreviewBody preview={preview} fileName={file.name} actions={false} />
    </Section>
  );
}

/**
 * A published file's preview, the content of its tab. Memoized on the file,
 * so streamed packets that change nothing in the panel do not render it.
 */
export const PublishedFilePreview = memo(function PublishedFilePreview({
  file,
}: PublishedFilePreviewProps) {
  return (
    <FilePreviewScope>
      <PublishedFilePreviewContent file={file} />
    </FilePreviewScope>
  );
});
