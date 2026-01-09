"use client";

import React, { useRef, useState, useEffect, useMemo } from "react";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import { ProjectFile } from "@/app/chat/projects/ProjectsContext";
import { formatRelativeTime } from "@/app/chat/components/projects/project_utils";
import Text from "@/refresh-components/texts/Text";
import type { IconProps } from "@opal/types";
import { getFileExtension, isImageExtension } from "@/lib/utils";
import { UserFileStatus } from "@/app/chat/projects/projectsService";
import CreateButton from "@/refresh-components/buttons/CreateButton";
import Button from "@/refresh-components/buttons/Button";
import IconButton from "@/refresh-components/buttons/IconButton";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import AttachmentButton from "@/refresh-components/buttons/AttachmentButton";
import Modal from "@/refresh-components/Modal";
import ScrollIndicatorDiv from "@/refresh-components/ScrollIndicatorDiv";
import { useModal } from "@/refresh-components/contexts/ModalContext";
import CounterSeparator from "@/refresh-components/CounterSeparator";
import useFilter from "@/hooks/useFilter";
import {
  SvgEye,
  SvgFiles,
  SvgFileText,
  SvgImage,
  SvgTrash,
  SvgXCircle,
} from "@opal/icons";

function getIcon(
  file: ProjectFile,
  isProcessing: boolean
): React.FunctionComponent<IconProps> {
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

  const Icon = getIcon(file, isProcessing);
  const description = getDescription(file);
  const rightText = file.last_accessed_at
    ? formatRelativeTime(file.last_accessed_at)
    : "";

  return (
    <AttachmentButton
      onClick={onClick}
      icon={Icon}
      description={description}
      rightText={rightText}
      selected={isSelected}
      processing={isProcessing}
      onView={onView}
      actionIcon={SvgTrash}
      onAction={onDelete}
    >
      {file.name}
    </AttachmentButton>
  );
}

export interface UserFilesModalProps {
  // Modal content
  title: string;
  description: string;
  recentFiles: ProjectFile[];
  handleUploadChange?: (e: React.ChangeEvent<HTMLInputElement>) => void;
  selectedFileIds?: string[];

  // FileAttachment related
  onView?: (file: ProjectFile) => void;
  onDelete?: (file: ProjectFile) => void;
  onPickRecent?: (file: ProjectFile) => void;
  onUnpickRecent?: (file: ProjectFile) => void;
}

export default function UserFilesModal({
  title,
  description,
  recentFiles,
  handleUploadChange,
  selectedFileIds,

  onView,
  onDelete,
  onPickRecent,
  onUnpickRecent,
}: UserFilesModalProps) {
  const { isOpen, toggle } = useModal();
  const [selectedIds, setSelectedIds] = useState<Set<string>>(
    () => new Set(selectedFileIds || [])
  );
  const [showOnlySelected, setShowOnlySelected] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const searchInputRef = useRef<HTMLInputElement | null>(null);
  const triggerUploadPicker = () => fileInputRef.current?.click();

  useEffect(() => {
    if (selectedFileIds) {
      setSelectedIds(new Set(selectedFileIds));
    } else {
      setSelectedIds(new Set());
    }
  }, [selectedFileIds]);

  const selectedCount = selectedIds.size;

  const handleDeselectAll = () => {
    selectedIds.forEach((id) => {
      const file = recentFiles.find((f) => f.id === id);
      if (file) {
        onUnpickRecent?.(file);
      }
    });
    setSelectedIds(new Set());
  };

  const files = useMemo(
    () =>
      showOnlySelected
        ? recentFiles.filter((projectFile) => selectedIds.has(projectFile.id))
        : recentFiles,
    [showOnlySelected, recentFiles, selectedIds]
  );

  const { query, setQuery, filtered } = useFilter(files, (file) => file.name);

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

      <Modal open={isOpen} onOpenChange={toggle}>
        <Modal.Content
          tall
          onOpenAutoFocus={(e) => {
            e.preventDefault();
            searchInputRef.current?.focus();
          }}
          preventAccidentalClose={false}
        >
          <Modal.Header icon={SvgFiles} title={title} description={description}>
            {/* Search bar section */}
            <div className="flex flex-row items-center gap-2">
              <InputTypeIn
                ref={searchInputRef}
                placeholder="Search files..."
                value={query}
                onChange={(e) => setQuery(e.target.value)}
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
          </Modal.Header>

          <Modal.Body className="flex flex-col flex-1 overflow-hidden bg-background-tint-01">
            {/* File display section */}
            {filtered.length === 0 ? (
              <div className="p-4 flex w-full h-full items-center justify-center">
                <Text as="p" text03>
                  No files found
                </Text>
              </div>
            ) : (
              <ScrollIndicatorDiv className="p-2 gap-2" variant="shadow">
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
                      onDelete={
                        onDelete ? () => onDelete(projectFle) : undefined
                      }
                    />
                  );
                })}

                {/* File count divider - only show when not searching or filtering */}
                {!query.trim() && !showOnlySelected && (
                  <CounterSeparator
                    count={recentFiles.length}
                    text={recentFiles.length === 1 ? "File" : "Files"}
                  />
                )}
              </ScrollIndicatorDiv>
            )}
          </Modal.Body>

          <Modal.Footer className="flex items-center justify-between p-4">
            {/* Left side: file count and controls */}
            {onPickRecent && (
              <div className="flex items-center gap-2">
                <Text as="p" text03>
                  {selectedCount} {selectedCount === 1 ? "file" : "files"}{" "}
                  selected
                </Text>
                <IconButton
                  icon={SvgEye}
                  internal
                  onClick={() => setShowOnlySelected(!showOnlySelected)}
                  className={showOnlySelected ? "bg-background-tint-02" : ""}
                />
                <IconButton
                  icon={SvgXCircle}
                  internal
                  onClick={handleDeselectAll}
                  disabled={selectedCount === 0}
                />
              </div>
            )}

            {/* Right side: Done button */}
            <Button secondary onClick={() => toggle(false)} className="ml-auto">
              Done
            </Button>
          </Modal.Footer>
        </Modal.Content>
      </Modal>
    </>
  );
}
