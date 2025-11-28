"use client";

import React, { useMemo } from "react";
import type { ProjectFile } from "@/app/chat/projects/projectsService";
import { UserFileStatus } from "@/app/chat/projects/projectsService";
import Text from "@/refresh-components/texts/Text";
import SvgFileText from "@/icons/file-text";
import Truncated from "@/refresh-components/texts/Truncated";
import { cn, isImageFile } from "@/lib/utils";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import SvgX from "@/icons/x";

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

  const sizeClass = compact ? "h-14 w-14" : "h-20 w-20";
  const loaderSize = compact ? "h-5 w-5" : "h-8 w-8";

  const doneUploading = String(file.status) !== UserFileStatus.UPLOADING;

  return (
    <div
      className={`relative group ${sizeClass} rounded-12 border border-border-01 ${
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
            "h-5",
            "w-5",
            "flex",
            "items-center",
            "justify-center",
            "rounded-[4px]",
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
          <SvgX className="h-4 w-4 stroke-text-inverted-03" />
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
          className="h-full w-full object-cover rounded-12"
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
  onFileClick,
  compactImages = false,
}: {
  file: ProjectFile;
  removeFile: (fileId: string) => void;
  onFileClick?: (file: ProjectFile) => void;
  compactImages?: boolean;
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

  const isProcessing =
    String(file.status) === UserFileStatus.UPLOADING ||
    String(file.status) === UserFileStatus.PROCESSING;

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

  // Regular file card layout for non-images or processing files
  return (
    <div
      className={`relative group flex items-center gap-3 border border-border-01 rounded-12 ${
        isProcessing ? "bg-background-neutral-02" : "bg-background-tint-00"
      } p-1 h-14 w-40 pl-2 ${
        onFileClick && !isProcessing
          ? "cursor-pointer hover:bg-accent-background"
          : ""
      }`}
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
          className="absolute -left-2 -top-2 z-10 h-5 w-5 flex items-center justify-center rounded-[4px] border border-border text-[11px] bg-background-neutral-inverted-01 text-text-inverted-05 shadow-sm opacity-0 group-hover:opacity-100 focus:opacity-100 pointer-events-none group-hover:pointer-events-auto focus:pointer-events-auto transition-opacity duration-150 hover:opacity-90"
        >
          <SvgX className="h-4 w-4 stroke-text-inverted-03" />
        </button>
      )}
      <div
        className={`flex h-9 w-9 items-center justify-center rounded-08 p-2
      ${isProcessing ? "bg-background-neutral-03" : "bg-background-tint-01"}`}
      >
        {isProcessing ? (
          <SimpleLoader />
        ) : (
          <SvgFileText className="h-5 w-5 stroke-text-02" />
        )}
      </div>
      <div className="flex flex-col overflow-hidden">
        <Truncated
          className={`font-secondary-action truncate
          ${isProcessing ? "text-text-03" : "text-text-04"}`}
          title={file.name}
        >
          {file.name}
        </Truncated>
        <Text text03 secondaryBody nowrap className="truncate">
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
  <div className="w-40 h-14 rounded-12 bg-background-tint-02 animate-pulse" />
);

// Grid component for displaying multiple images compactly
export function ImageGrid({
  files,
  removeFile,
  onFileClick,
}: {
  files: ProjectFile[];
  removeFile: (fileId: string) => void;
  onFileClick?: (file: ProjectFile) => void;
}) {
  return (
    <div className="grid grid-cols-4 gap-1 p-1 rounded-12 border border-border-01 bg-background-tint-00">
      {files.map((file) => {
        const imageUrl = file.file_id ? `/api/chat/file/${file.file_id}` : null;
        const isProcessing =
          String(file.status) === UserFileStatus.UPLOADING ||
          String(file.status) === UserFileStatus.PROCESSING;

        return (
          <ImageFileCard
            key={file.id}
            file={file}
            imageUrl={imageUrl}
            removeFile={removeFile}
            onFileClick={onFileClick}
            isProcessing={isProcessing}
            compact
          />
        );
      })}
    </div>
  );
}
