"use client";

import type { RichStr } from "@opal/types";
import { memo, useMemo } from "react";
import { useTranslations } from "next-intl";
import { Button, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import { SvgFiles } from "@opal/icons";
import type { PublishedFile } from "@/app/app/services/streamingModels";
import { buildImgUrl } from "@/app/app/components/files/images/utils";
import { getFileIcon } from "@/lib/utils";
import { downloadFile } from "@/lib/download";
import {
  filesSharingALabel,
  publishedFileLabel,
  publishedFilePath,
} from "@/lib/chat/publishedFiles";
import { WorkspaceHome } from "@/sections/output-panel/WorkspaceHome";
import {
  OutputImageThumbnail,
  OutputTileFrame,
  OutputTileGrid,
} from "@/sections/output-panel/OutputTile";
import {
  ChatFilePreviewBody,
  useChatFilePreview,
} from "@/sections/modals/PreviewModal/ChatFilePreview";

const IMAGE_FILE = /\.(png|jpe?g|gif|webp|svg|avif)$/i;

interface PublishedFilesGridProps {
  // The newest publish of each path, newest first
  files: PublishedFile[];
  // Files to mark with Craft's new-file marker
  unseenFileIds: string[];
  // Shown in place of the tiles when `files` is empty
  emptyLabel?: string | RichStr;
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
      {files.length === 0 && emptyLabel && (
        <div role="status" className="text-center">
          <Text font="main-ui-muted" color="text-03">
            {emptyLabel}
          </Text>
        </div>
      )}
      <OutputTileGrid>
        {files.map((file) => {
          const label = publishedFileLabel(file);
          const FileIcon = getFileIcon(file.name);
          const icon = (
            <FileIcon
              size={32}
              className="size-8 stroke-text-03 @[40rem]:size-10 [&_*]:stroke-1"
            />
          );
          return (
            <div key={file.file_id} data-published-file={file.file_id}>
              <OutputTileFrame
                label={t("filesTab.tile.ariaLabel", { name: label })}
                name={
                  sharingALabel.has(file.file_id)
                    ? publishedFilePath(file)
                    : label
                }
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
                  ) : (
                    icon
                  )
                }
              />
            </div>
          );
        })}
      </OutputTileGrid>
    </WorkspaceHome>
  );
});

interface PublishedFilePreviewProps {
  file: PublishedFile;
}

/**
 * A published file's preview, the content of its tab. Memoized on the file,
 * so streamed packets that change nothing in the panel do not render it.
 */
export const PublishedFilePreview = memo(function PublishedFilePreview({
  file,
}: PublishedFilePreviewProps) {
  const t = useTranslations("chat.publishedFiles");
  const presentingDocument = useMemo(
    () => ({ document_id: file.file_id, semantic_identifier: file.name }),
    [file.file_id, file.name]
  );
  const preview = useChatFilePreview(presentingDocument);

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
      <ChatFilePreviewBody preview={preview} />
    </Section>
  );
});

interface PublishedFilesButtonProps {
  pressed: boolean;
  onClick: () => void;
}

/** Opens and closes the published files panel. */
export function PublishedFilesButton({
  pressed,
  onClick,
}: PublishedFilesButtonProps) {
  const t = useTranslations("chat.publishedFiles");

  return (
    <Button
      icon={SvgFiles}
      prominence="tertiary"
      interaction={pressed ? "hover" : "rest"}
      responsiveHideText
      onClick={onClick}
      tooltip={t("openButton.tooltip")}
      aria-label={t("openButton.label")}
      aria-pressed={pressed}
    >
      {t("openButton.label")}
    </Button>
  );
}
