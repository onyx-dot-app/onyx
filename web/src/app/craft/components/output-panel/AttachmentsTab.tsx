"use client";

import { useState, useEffect, useCallback } from "react";
import useSWR from "swr";
import {
  useBuildSessionStore,
  useFilesNeedsRefresh,
} from "@/app/craft/hooks/useBuildSessionStore";
import {
  fetchDirectoryListing,
  deleteFile,
} from "@/app/craft/services/apiServices";
import { FileSystemEntry } from "@/app/craft/types/streamingTypes";
import { cn, isImageFile, getFileIcon, formatBytes } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import Button from "@/refresh-components/buttons/Button";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import { Section } from "@/layouts/general-layouts";
import { SvgPaperclip, SvgTrash, SvgX } from "@opal/icons";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface AttachmentsTabProps {
  sessionId: string | null;
  onFileClick?: (path: string, fileName: string) => void;
}

// ---------------------------------------------------------------------------
// AttachmentTile (internal)
// ---------------------------------------------------------------------------

interface AttachmentTileProps {
  entry: FileSystemEntry;
  sessionId: string;
  onRemove: () => void;
  onClick?: () => void;
}

function AttachmentTile({
  entry,
  sessionId,
  onRemove,
  onClick,
}: AttachmentTileProps) {
  const isImage = isImageFile(entry.name);
  const [imgError, setImgError] = useState(false);

  const encodedPath = entry.path
    .split("/")
    .map((segment) => encodeURIComponent(segment))
    .join("/");
  const thumbnailUrl = `/api/build/sessions/${sessionId}/artifacts/${encodedPath}`;

  const Icon = getFileIcon(entry.name);

  const extension = entry.name.includes(".")
    ? entry.name.slice(entry.name.lastIndexOf(".") + 1).toUpperCase()
    : "";

  return (
    <div className="group/tile relative">
      <div
        onClick={onClick}
        className={cn(
          "relative flex flex-col overflow-hidden",
          "border border-border-01 rounded-12",
          "bg-background-tint-00",
          "hover:border-border-02 hover:bg-background-tint-02",
          "transition-colors duration-150",
          onClick && "cursor-pointer"
        )}
      >
        {/* Remove button */}
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
          title="Remove"
          aria-label="Remove"
          className={cn(
            "absolute right-1.5 top-1.5 z-10 h-5 w-5",
            "flex items-center justify-center",
            "rounded-full bg-background-neutral-00 border border-border-02",
            "opacity-0 group-hover/tile:opacity-100 focus:opacity-100",
            "pointer-events-none group-hover/tile:pointer-events-auto focus:pointer-events-auto",
            "transition-opacity duration-150 hover:bg-background-tint-03"
          )}
        >
          <SvgX size={10} className="stroke-text-03" />
        </button>

        {/* Thumbnail area */}
        <div className="h-24 w-full flex items-center justify-center bg-background-neutral-02">
          {isImage && !imgError ? (
            <img
              src={thumbnailUrl}
              alt={entry.name}
              className="h-full w-full object-cover"
              onError={() => setImgError(true)}
            />
          ) : (
            <div className="flex flex-col items-center gap-1">
              <Icon size={28} className="stroke-text-02" />
              {extension && (
                <Text figureSmallLabel text02>
                  {extension}
                </Text>
              )}
            </div>
          )}
        </div>

        {/* File info */}
        <div className="flex flex-col gap-0.5 p-2 min-w-0">
          <Text secondaryAction text04 className="truncate">
            {entry.name}
          </Text>
          {entry.size != null && (
            <Text figureSmallLabel text02>
              {formatBytes(entry.size)}
            </Text>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// AttachmentsTab
// ---------------------------------------------------------------------------

export default function AttachmentsTab({
  sessionId,
  onFileClick,
}: AttachmentsTabProps) {
  const [fileToDelete, setFileToDelete] = useState<FileSystemEntry | null>(
    null
  );
  const [isDeleting, setIsDeleting] = useState(false);

  const triggerFilesRefresh = useBuildSessionStore(
    (state) => state.triggerFilesRefresh
  );

  // Fetch attachments directory listing
  const { data, error, isLoading, mutate } = useSWR(
    sessionId ? `build-attachments-${sessionId}` : null,
    () => (sessionId ? fetchDirectoryListing(sessionId, "attachments") : null),
    {
      revalidateOnFocus: true,
      dedupingInterval: 2000,
    }
  );

  // Auto-refresh when files are uploaded
  const filesNeedsRefresh = useFilesNeedsRefresh();

  useEffect(() => {
    if (filesNeedsRefresh > 0 && sessionId && mutate) {
      mutate();
    }
  }, [filesNeedsRefresh, sessionId, mutate]);

  // Filter to only files (no directories)
  const attachments = (data?.entries ?? []).filter(
    (entry) => !entry.is_directory
  );

  const handleDelete = useCallback(async () => {
    if (!sessionId || !fileToDelete) return;
    setIsDeleting(true);
    try {
      await deleteFile(sessionId, fileToDelete.path);
      await mutate();
      triggerFilesRefresh(sessionId);
      setFileToDelete(null);
    } catch (err) {
      console.error("Failed to delete attachment:", err);
    } finally {
      setIsDeleting(false);
    }
  }, [sessionId, fileToDelete, mutate, triggerFilesRefresh]);

  // No session state
  if (!sessionId) {
    return (
      <Section
        height="full"
        alignItems="center"
        justifyContent="center"
        padding={2}
      >
        <SvgPaperclip size={48} className="stroke-text-02" />
        <Text headingH3 text03>
          No attachments yet
        </Text>
        <Text secondaryBody text02>
          Upload files to your build to see them here
        </Text>
      </Section>
    );
  }

  // Loading state
  if (isLoading) {
    return (
      <Section
        height="full"
        alignItems="center"
        justifyContent="center"
        padding={2}
      >
        <SimpleLoader className="h-6 w-6" />
        <Text secondaryBody text02>
          Loading attachments...
        </Text>
      </Section>
    );
  }

  // Error state
  if (error) {
    return (
      <Section
        height="full"
        alignItems="center"
        justifyContent="center"
        padding={2}
      >
        <SvgPaperclip size={48} className="stroke-text-02" />
        <Text headingH3 text03>
          Could not load attachments
        </Text>
        <Text secondaryBody text02>
          Try refreshing the panel
        </Text>
      </Section>
    );
  }

  // Empty state
  if (attachments.length === 0) {
    return (
      <Section
        height="full"
        alignItems="center"
        justifyContent="center"
        padding={2}
      >
        <SvgPaperclip size={48} className="stroke-text-02" />
        <Text headingH3 text03>
          No attachments
        </Text>
        <Text secondaryBody text02>
          Files you upload will appear here
        </Text>
      </Section>
    );
  }

  return (
    <>
      <div className="flex-1 overflow-auto overlay-scrollbar h-full">
        <div
          className="grid gap-3 p-3"
          style={{
            gridTemplateColumns: "repeat(auto-fill, minmax(10rem, 1fr))",
          }}
        >
          {attachments.map((entry) => (
            <AttachmentTile
              key={entry.path}
              entry={entry}
              sessionId={sessionId}
              onRemove={() => setFileToDelete(entry)}
              onClick={
                onFileClick
                  ? () => onFileClick(entry.path, entry.name)
                  : undefined
              }
            />
          ))}
        </div>
      </div>

      {/* Delete confirmation modal */}
      {fileToDelete && (
        <ConfirmationModalLayout
          title="Delete attachment"
          icon={SvgTrash}
          onClose={isDeleting ? undefined : () => setFileToDelete(null)}
          hideCancel={isDeleting}
          submit={
            <Button
              danger
              onClick={handleDelete}
              disabled={isDeleting}
              leftIcon={isDeleting ? SimpleLoader : undefined}
            >
              {isDeleting ? "Deleting..." : "Delete"}
            </Button>
          }
        >
          {`Are you sure you want to delete "${fileToDelete.name}"? This action cannot be undone.`}
        </ConfirmationModalLayout>
      )}
    </>
  );
}
