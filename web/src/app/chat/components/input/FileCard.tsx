"use client";

import React, { useMemo } from "react";
import type { ProjectFile } from "@/app/chat/projects/projectsService";
import { UserFileStatus } from "@/app/chat/projects/projectsService";
import Text from "@/refresh-components/texts/Text";
import Truncated from "@/refresh-components/texts/Truncated";
import { cn, isImageFile } from "@/lib/utils";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import { SvgFileText, SvgX } from "@opal/icons";
function ImageFileCard({
  file,
  imageUrl,
  removeFile,
  onFileClick,
  isProcessing = false,
  compact = false,
}: {
  file: ProjectFile;
  imageUrl: string | null;
  removeFile: (fileId: string) => void;
  onFileClick?: (file: ProjectFile) => void;
  isProcessing?: boolean;
  compact?: boolean;
}) {
  const handleRemoveFile = async (e: React.MouseEvent) => {
    e.stopPropagation();
    removeFile(file.id);
  };

  const sizeClass = compact ? "h-11 w-11" : "h-20 w-20";
  const loaderSize = compact ? "h-5 w-5" : "h-8 w-8";

  const doneUploading = String(file.status) !== UserFileStatus.UPLOADING;

  return (
    <div
      className={`relative group ${sizeClass} rounded-08 border border-border-01 ${
        isProcessing ? "bg-background-neutral-02" : ""
      } ${
        onFileClick && !isProcessing ? "cursor-pointer hover:opacity-90" : ""
      }`}
      onClick={() => {
        if (onFileClick && !isProcessing) {
          onFileClick(file);
        }
      }}
    >
      {doneUploading && (
        <button
          onClick={handleRemoveFile}
          title="Delete file"
          aria-label="Delete file"
          className={cn(
            "absolute",
            "-left-2",
            "-top-2",
            "z-10",
            "h-4",
            "w-4",
            "flex",
            "items-center",
            "justify-center",
            "rounded-04",
            "border",
            "border-border",
            "text-[11px]",
            "bg-background-neutral-inverted-01",
            "text-text-inverted-05",
            "shadow-sm",
            "opacity-0",
            "group-hover:opacity-100",
            "focus:opacity-100",
            "pointer-events-none",
            "group-hover:pointer-events-auto",
            "focus:pointer-events-auto",
            "transition-opacity",
            "duration-150",
            "hover:opacity-90"
          )}
        >
          <SvgX className="h-3 w-3 stroke-text-inverted-03" />
        </button>
      )}
      {!doneUploading || !imageUrl ? (
        <div className="h-full w-full flex items-center justify-center">
          <SimpleLoader className={loaderSize} />
        </div>
      ) : (
        <img
          src={imageUrl}
          alt={file.name}
          className="h-full w-full object-cover rounded-08"
          onError={(e) => {
            // Fallback to regular file card if image fails to load
            const target = e.target as HTMLImageElement;
            target.style.display = "none";
          }}
        />
      )}
    </div>
  );
}

export function FileCard({
  file,
  removeFile,
  hideProcessingState = false,
  onFileClick,
  compactImages = false,
  className,
}: {
  file: ProjectFile;
  removeFile: (fileId: string) => void;
  hideProcessingState?: boolean;
  onFileClick?: (file: ProjectFile) => void;
  compactImages?: boolean;
  className?: string;
}) {
  const typeLabel = useMemo(() => {
    const name = String(file.name || "");
    const lastDotIndex = name.lastIndexOf(".");
    if (lastDotIndex <= 0 || lastDotIndex === name.length - 1) {
      return "";
    }
    return name.slice(lastDotIndex + 1).toUpperCase();
  }, [file.name]);

  const isImage = useMemo(() => {
    return isImageFile(file.name);
  }, [file.name]);

  const imageUrl = useMemo(() => {
    if (isImage && file.file_id) {
      return `/api/chat/file/${file.file_id}`;
    }
    return null;
  }, [isImage, file.file_id]);

  const isActuallyProcessing =
    String(file.status) === UserFileStatus.UPLOADING ||
    String(file.status) === UserFileStatus.PROCESSING;

  // When hideProcessingState is true, we treat processing files as completed for display purposes
  const isProcessing = hideProcessingState ? false : isActuallyProcessing;

  const handleRemoveFile = async (e: React.MouseEvent) => {
    e.stopPropagation();
    removeFile(file.id);
  };

  // For images, always show the larger preview layout (even while processing)
  if (isImage) {
    return (
      <ImageFileCard
        file={file}
        imageUrl={imageUrl}
        removeFile={removeFile}
        onFileClick={onFileClick}
        isProcessing={isProcessing}
        compact={compactImages}
      />
    );
  }

  return (
    <div
      className={cn(
        "relative group flex items-center gap-1 border border-border-01 rounded-08",
        isProcessing ? "bg-background-neutral-02" : "bg-background-tint-00",
        "p-1 h-11 min-w-[120px] max-w-[240px]",
        onFileClick &&
          !isProcessing &&
          "cursor-pointer hover:bg-accent-background",
        className
      )}
      onClick={() => {
        if (onFileClick && !isProcessing) {
          onFileClick(file);
        }
      }}
    >
      {String(file.status) !== UserFileStatus.UPLOADING && (
        <button
          onClick={handleRemoveFile}
          title="Delete file"
          aria-label="Delete file"
          className="absolute -left-[5px] -top-[5px] z-10 h-4 w-4 flex items-center justify-center rounded-04 border border-border text-[11px] bg-background-neutral-inverted-01 text-text-inverted-05 shadow-sm opacity-0 group-hover:opacity-100 focus:opacity-100 pointer-events-none group-hover:pointer-events-auto focus:pointer-events-auto transition-opacity duration-150 hover:opacity-90"
        >
          <SvgX className="h-3 w-3 stroke-text-inverted-03" />
        </button>
      )}
      <div
        className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-04 p-2
      ${isProcessing ? "bg-background-neutral-03" : "bg-background-tint-01"}`}
      >
        {isProcessing ? (
          <SimpleLoader />
        ) : (
          <SvgFileText className="h-5 w-5 stroke-text-02" />
        )}
      </div>
      <div className="flex flex-col overflow-hidden pr-1">
        <Truncated
          className={`font-secondary-action truncate
          ${isProcessing ? "text-text-03" : "text-text-04"}`}
          title={file.name}
        >
          {file.name}
        </Truncated>
        <Text as="p" text03 secondaryBody nowrap className="truncate">
          {isProcessing
            ? file.status === UserFileStatus.UPLOADING
              ? "Uploading..."
              : "Processing..."
            : typeLabel}
        </Text>
      </div>
    </div>
  );
}

// Skeleton loading component for file cards
export const FileCardSkeleton = () => (
  <div className="min-w-[120px] max-w-[240px] h-11 rounded-08 bg-background-tint-02 animate-pulse" />
);
