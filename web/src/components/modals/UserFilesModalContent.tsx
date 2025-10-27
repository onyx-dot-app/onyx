"use client";

import React, { useMemo, useRef, useState, useEffect } from "react";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import IconButton from "@/refresh-components/buttons/IconButton";
import { ProjectFile } from "@/app/chat/projects/ProjectsContext";
import { formatRelativeTime } from "@/app/chat/components/projects/project_utils";
import Text from "@/refresh-components/texts/Text";
import SvgX from "@/icons/x";
import { SvgProps } from "@/icons";
import SvgFileText from "@/icons/file-text";
import SvgImage from "@/icons/image";
import { getFileExtension, isImageExtension } from "@/lib/utils";
import { UserFileStatus } from "@/app/chat/projects/projectsService";
import CreateButton from "@/refresh-components/buttons/CreateButton";
import VerticalShadowScroller from "@/refresh-components/VerticalShadowScroller";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import AttachmentButton from "@/refresh-components/buttons/AttachmentButton";

function getIcon(
  file: ProjectFile,
  isProcessing: boolean,
  isSelected: boolean
): React.FunctionComponent<SvgProps> {
  if (isProcessing) return SimpleLoader;
  const ext = getFileExtension(file.name).toLowerCase();
  if (isImageExtension(ext)) return SvgImage;
  return SvgFileText;
}

function getDescription(file: ProjectFile): string {
  const s = String(file.status || "");
  const typeLabel = getFileExtension(file.name);
  if (s === UserFileStatus.PROCESSING) return "Processing...";
  if (s === UserFileStatus.UPLOADING) return "Uploading...";
  if (s === UserFileStatus.DELETING) return "Deleting...";
  if (s === UserFileStatus.COMPLETED) return typeLabel;
  return file.status ?? typeLabel;
}

interface FileAttachmentProps {
  file: ProjectFile;
  isSelected: boolean;
  onClick?: () => void;
  onView?: () => void;
  onDelete?: () => void;
}

function FileAttachment({
  file,
  isSelected,
  onClick,
  onView,
  onDelete,
}: FileAttachmentProps) {
  const isProcessing =
    String(file.status) === UserFileStatus.PROCESSING ||
    String(file.status) === UserFileStatus.UPLOADING ||
    String(file.status) === UserFileStatus.DELETING;

  const LeftIcon = getIcon(file, isProcessing, isSelected);
  const description = getDescription(file);
  const rightText = file.last_accessed_at
    ? formatRelativeTime(file.last_accessed_at)
    : "";

  return (
    <AttachmentButton
      onClick={onClick}
      leftIcon={LeftIcon}
      description={description}
      rightText={rightText}
      selected={isSelected}
      processing={isProcessing}
      onView={onView}
      onDelete={onDelete}
    >
      {file.name}
    </AttachmentButton>
  );
}

export interface UserFilesModalProps {
  // Modal related
  title: string;
  description: string;
  icon: React.FunctionComponent<SvgProps>;
  recentFiles: ProjectFile[];
  handleUploadChange?: (e: React.ChangeEvent<HTMLInputElement>) => void;
  onClose?: () => void;
  selectedFileIds?: string[];

  // FileAttachment related
  onView?: (file: ProjectFile) => void;
  onDelete?: (file: ProjectFile) => void;
  onPickRecent?: (file: ProjectFile) => void;
  onUnpickRecent?: (file: ProjectFile) => void;
}

export default function UserFilesModalContent({
  title,
  description,
  icon: Icon,
  recentFiles,
  handleUploadChange,
  onClose,
  selectedFileIds,

  onView,
  onDelete,
  onPickRecent,
  onUnpickRecent,
}: UserFilesModalProps) {
  const [search, setSearch] = useState("");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(
    () => new Set(selectedFileIds || [])
  );
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const triggerUploadPicker = () => fileInputRef.current?.click();

  useEffect(() => {
    if (selectedFileIds) {
      setSelectedIds(new Set(selectedFileIds));
    } else {
      setSelectedIds(new Set());
    }
  }, [selectedFileIds]);

  const filtered = useMemo(() => {
    const s = search.trim().toLowerCase();
    if (!s) return recentFiles;
    return recentFiles.filter((f) => f.name.toLowerCase().includes(s));
  }, [recentFiles, search]);

  return (
    <>
      {/* Hidden file input */}
      {handleUploadChange && (
        <input
          ref={fileInputRef}
          type="file"
          multiple
          className="hidden"
          onChange={handleUploadChange}
        />
      )}

      {/* Title section */}
      <div className="flex flex-col gap-1 px-4 pt-4">
        <div className="h-[1.5rem] flex flex-row justify-between items-center w-full">
          <Icon className="w-[1.5rem] h-[1.5rem] stroke-text-04" />
          {onClose && <IconButton icon={SvgX} internal onClick={onClose} />}
        </div>
        <Text headingH3 text04 className="w-full text-left">
          {title}
        </Text>
        <Text text03>{description}</Text>
      </div>

      {/* Search bar section */}
      <div className="flex items-center gap-2 p-3">
        <InputTypeIn
          placeholder="Search files..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          leftSearchIcon
          autoComplete="off"
          tabIndex={0}
          onFocus={(e) => {
            e.target.select();
          }}
        />
        {handleUploadChange && (
          <CreateButton
            onClick={triggerUploadPicker}
            secondary={false}
            internal
          >
            Add Files
          </CreateButton>
        )}
      </div>

      {/* File display section */}
      <div className="bg-background-tint-01 overflow-y-scroll">
        {filtered.length === 0 ? (
          <div className="p-4 flex w-full h-full items-center justify-center">
            <Text text03>No files found</Text>
          </div>
        ) : (
          <VerticalShadowScroller className="p-2 flex flex-col gap-2 overflow-scroll max-h-[20rem]">
            {filtered.map((projectFle) => {
              const isSelected = selectedIds.has(projectFle.id);
              return (
                <FileAttachment
                  key={projectFle.id}
                  file={projectFle}
                  isSelected={isSelected}
                  onClick={
                    onPickRecent
                      ? () => {
                          if (isSelected) {
                            onUnpickRecent?.(projectFle);
                            setSelectedIds((prev) => {
                              const next = new Set(prev);
                              next.delete(projectFle.id);
                              return next;
                            });
                          } else {
                            onPickRecent(projectFle);
                            setSelectedIds((prev) => {
                              const next = new Set(prev);
                              next.add(projectFle.id);
                              return next;
                            });
                          }
                        }
                      : undefined
                  }
                  onView={onView ? () => onView(projectFle) : undefined}
                  onDelete={onDelete ? () => onDelete(projectFle) : undefined}
                />
              );
            })}
          </VerticalShadowScroller>
        )}
      </div>
    </>
  );
}
