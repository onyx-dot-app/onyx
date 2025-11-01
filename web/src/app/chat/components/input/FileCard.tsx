"use client";

import React, { useMemo } from "react";
import { Loader2, X } from "lucide-react";
import type { ProjectFile } from "../../projects/projectsService";
import { UserFileStatus } from "../../projects/projectsService";
import Text from "@/refresh-components/texts/Text";
import SvgFileText from "@/icons/file-text";
import Truncated from "@/refresh-components/texts/Truncated";

function ImageFileCard({
  file,
  imageUrl,
  removeFile,
  onFileClick,
}: {
  file: ProjectFile;
  imageUrl: string;
  removeFile: (fileId: string) => void;
  onFileClick?: (file: ProjectFile) => void;
}) {
  const handleRemoveFile = async (e: React.MouseEvent) => {
    e.stopPropagation();
    removeFile(file.id);
  };

  return (
    <div
      className={`relative group h-20 w-20 ${
        onFileClick ? "cursor-pointer hover:opacity-90" : ""
      }`}
      onClick={() => {
        if (onFileClick) {
          onFileClick(file);
        }
      }}
    >
      {String(file.status) !== UserFileStatus.UPLOADING && (
        <button
          onClick={handleRemoveFile}
          title="Delete file"
          aria-label="Delete file"
          className="absolute -left-2 -top-2 z-10 h-5 w-5 flex items-center justify-center rounded-[4px] border border-border text-[11px] bg-[#1f1f1f] text-white dark:bg-[#fefcfa] dark:text-black shadow-sm opacity-0 group-hover:opacity-100 focus:opacity-100 pointer-events-none group-hover:pointer-events-auto focus:pointer-events-auto transition-opacity duration-150 hover:opacity-90"
        >
          <X className="h-4 w-4 dark:text-dark-tremor-background-muted" />
        </button>
      )}
      <img
        src={imageUrl}
        alt={file.name}
        className="h-full w-full object-cover rounded-12 border border-border-01"
        onError={(e) => {
          // Fallback to regular file card if image fails to load
          const target = e.target as HTMLImageElement;
          target.style.display = "none";
        }}
      />
    </div>
  );
}

export function FileCard({
  file,
  removeFile,
  hideProcessingState = false,
  onFileClick,
}: {
  file: ProjectFile;
  removeFile: (fileId: string) => void;
  hideProcessingState?: boolean;
  onFileClick?: (file: ProjectFile) => void;
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
    const imageExtensions = [
      ".jpg",
      ".jpeg",
      ".png",
      ".gif",
      ".bmp",
      ".webp",
      ".svg",
    ];
    const fileName = String(file.name || "").toLowerCase();
    return imageExtensions.some((ext) => fileName.endsWith(ext));
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

  // For images, show a larger preview without metadata
  if (isImage && imageUrl && !isProcessing) {
    return (
      <ImageFileCard
        file={file}
        imageUrl={imageUrl}
        removeFile={removeFile}
        onFileClick={onFileClick}
      />
    );
  }

  // Regular file card layout for non-images or processing files
  return (
    <div
      className={`relative group flex items-center gap-3 border border-border-01 rounded-12 ${
        isProcessing ? "bg-background-neutral-02" : "bg-background-tint-00"
      } p-1 h-14 w-40 ${
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
          className="absolute -left-2 -top-2 z-10 h-5 w-5 flex items-center justify-center rounded-[4px] border border-border text-[11px] bg-[#1f1f1f] text-white dark:bg-[#fefcfa] dark:text-black shadow-sm opacity-0 group-hover:opacity-100 focus:opacity-100 pointer-events-none group-hover:pointer-events-auto focus:pointer-events-auto transition-opacity duration-150 hover:opacity-90"
        >
          <X className="h-4 w-4 dark:text-dark-tremor-background-muted" />
        </button>
      )}
      <div
        className={`flex h-9 w-9 items-center justify-center rounded-08 p-2
      ${isProcessing ? "bg-background-neutral-03" : "bg-background-tint-01"}`}
      >
        {isProcessing || file.status === UserFileStatus.UPLOADING ? (
          <Loader2 className="h-5 w-5 text-text-01 animate-spin" />
        ) : isImage && imageUrl ? (
          <img
            src={imageUrl}
            alt={file.name}
            className="h-full w-full object-cover rounded-08"
            onError={(e) => {
              // Fallback to file icon if image fails to load
              const target = e.target as HTMLImageElement;
              target.style.display = "none";
              const parent = target.parentElement;
              if (parent) {
                parent.classList.add(
                  "bg-background-tint-01",
                  "p-spacing-interline"
                );
                const icon = document.createElement("div");
                icon.innerHTML = '<svg class="h-5 w-5 stroke-text-02" />';
                parent.appendChild(icon);
              }
            }}
          />
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
