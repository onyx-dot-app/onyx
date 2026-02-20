"use client";

import { useMemo, useState } from "react";
import type { ProjectFile } from "@/app/app/projects/projectsService";
import { UserFileStatus } from "@/app/app/projects/projectsService";
import { cn, isImageFile } from "@/lib/utils";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import { SvgFileText, SvgX } from "@opal/icons";
import { Interactive } from "@opal/core";
import { AttachmentItemLayout } from "@/layouts/general-layouts";
import Spacer from "@/refresh-components/Spacer";

interface RemovableProps {
  onRemove?: () => void;
  children: React.ReactNode;
}

function Removable({ onRemove, children }: RemovableProps) {
  if (!onRemove) {
    return <>{children}</>;
  }

  return (
    <div className="relative group">
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          onRemove();
        }}
        title="Remove"
        aria-label="Remove"
        className={cn(
          "absolute -left-2 -top-2 z-10 h-4 w-4",
          "flex items-center justify-center",
          "rounded-04 border border-border text-[11px]",
          "bg-background-neutral-inverted-01 text-text-inverted-05 shadow-sm",
          "opacity-0 group-hover:opacity-100 focus:opacity-100",
          "pointer-events-none group-hover:pointer-events-auto focus:pointer-events-auto",
          "transition-opacity duration-150 hover:opacity-90"
        )}
      >
        <SvgX className="h-3 w-3 stroke-text-inverted-03" />
      </button>
      {children}
    </div>
  );
}

interface ImageFileCardProps {
  file: ProjectFile;
  imageUrl: string | null;
  removeFile?: (fileId: string) => void;
  onFileClick?: (file: ProjectFile) => void;
  isProcessing?: boolean;
  compact?: boolean;
}
function ImageFileCard({
  file,
  imageUrl,
  removeFile,
  onFileClick,
  isProcessing = false,
  compact = false,
}: ImageFileCardProps) {
  const sizeClass = compact ? "h-11 w-11" : "h-20 w-20";
  const loaderSize = compact ? "h-5 w-5" : "h-8 w-8";
  const iconSize = compact ? "h-5 w-5" : "h-8 w-8";
  const [imgError, setImgError] = useState(false);

  const doneUploading = String(file.status) !== UserFileStatus.UPLOADING;

  return (
    <Removable
      onRemove={
        removeFile && doneUploading ? () => removeFile(file.id) : undefined
      }
    >
      <div
        className={cn(
          sizeClass,
          "rounded-08 border border-border-01",
          isProcessing && "bg-background-neutral-02",
          onFileClick && !isProcessing && "cursor-pointer hover:opacity-90"
        )}
        onClick={() => {
          if (onFileClick && !isProcessing) {
            onFileClick(file);
          }
        }}
      >
        {!doneUploading || !imageUrl ? (
          <div className="h-full w-full flex items-center justify-center">
            <SimpleLoader className={loaderSize} />
          </div>
        ) : imgError ? (
          <div className="h-full w-full flex items-center justify-center">
            <SvgFileText className={iconSize} />
          </div>
        ) : (
          <img
            src={imageUrl}
            alt={file.name}
            className="h-full w-full object-cover rounded-08"
            onError={() => setImgError(true)}
          />
        )}
      </div>
    </Removable>
  );
}

export interface FileCardProps {
  file: ProjectFile;
  removeFile?: (fileId: string) => void;
  hideProcessingState?: boolean;
  onFileClick?: (file: ProjectFile) => void;
  compactImages?: boolean;
}
export function FileCard({
  file,
  removeFile,
  hideProcessingState = false,
  onFileClick,
  compactImages = false,
}: FileCardProps) {
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

  const doneUploading = String(file.status) !== UserFileStatus.UPLOADING;

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
    <Removable
      onRemove={
        removeFile && doneUploading ? () => removeFile(file.id) : undefined
      }
    >
      <div className="max-w-[12rem]">
        <Interactive.Container border heightVariant="fit">
          <AttachmentItemLayout
            icon={isProcessing ? SimpleLoader : SvgFileText}
            title={file.name}
            description={
              isProcessing
                ? file.status === UserFileStatus.UPLOADING
                  ? "Uploading..."
                  : "Processing..."
                : typeLabel
            }
          />
          <Spacer horizontal rem={0.5} />
        </Interactive.Container>
      </div>
    </Removable>
  );
}

// Skeleton loading component for file cards
export function FileCardSkeleton() {
  return (
    <div className="min-w-[120px] max-w-[240px] h-11 rounded-08 bg-background-tint-02 animate-pulse" />
  );
}
