"use client";

import React, { useMemo, useRef, useState, useEffect } from "react";
import { Modal } from "@/refresh-components/modals/NewModal";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import { ProjectFile } from "@/app/chat/projects/ProjectsContext";
import { formatRelativeTime } from "@/app/chat/components/projects/project_utils";
import Text from "@/refresh-components/texts/Text";
import { SvgProps } from "@/icons";
import SvgFileText from "@/icons/file-text";
import SvgImage from "@/icons/image";
import SvgEye from "@/icons/eye";
import SvgX from "@/icons/x";
import SvgXCircle from "@/icons/x-circle";
import { getFileExtension, isImageExtension } from "@/lib/utils";
import { UserFileStatus } from "@/app/chat/projects/projectsService";
import CreateButton from "@/refresh-components/buttons/CreateButton";
import OverflowDiv from "@/refresh-components/OverflowDiv";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import AttachmentButton from "@/refresh-components/buttons/AttachmentButton";
import Button from "@/refresh-components/buttons/Button";
import IconButton from "@/refresh-components/buttons/IconButton";
import ScrollIndicatorDiv from "@/refresh-components/ScrollIndicatorDiv";

function getIcon(
  file: ProjectFile,
  isProcessing: boolean
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

  const LeftIcon = getIcon(file, isProcessing);
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
  // Modal state
  open: boolean;
  onOpenChange: (open: boolean) => void;

  // Content
  title: string;
  description: string;
  icon: React.FunctionComponent<SvgProps>;
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
  open,
  onOpenChange,
  title,
  description,
  icon: Icon,
  recentFiles,
  handleUploadChange,
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

  const filtered = useMemo(() => {
    let files = recentFiles;

    // Filter by selected if toggled
    if (showOnlySelected) {
      files = files.filter((f) => selectedIds.has(f.id));
    }

    // Filter by search
    const s = search.trim().toLowerCase();
    if (!s) return files;
    return files.filter((f) => f.name.toLowerCase().includes(s));
  }, [recentFiles, search, showOnlySelected, selectedIds]);

  const handleDeselectAll = () => {
    selectedIds.forEach((id) => {
      const file = recentFiles.find((f) => f.id === id);
      if (file && onUnpickRecent) {
        onUnpickRecent(file);
      }
    });
    setSelectedIds(new Set());
  };

  const selectedCount = selectedIds.size;

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

      <Modal open={open} onOpenChange={onOpenChange}>
        <Modal.Content
          size="sm"
          onOpenAutoFocus={(e) => {
            e.preventDefault();
            searchInputRef.current?.focus();
            searchInputRef.current?.select();
          }}
        >
          <Modal.CloseButton />

          <Modal.Header className="flex flex-col gap-3 pb-2">
            {/* Icon, Title, Description */}
            <div className="flex flex-col gap-1 px-4 pt-4">
              <Modal.Icon icon={Icon} />
              <div className="flex flex-col">
                <Modal.Title>{title}</Modal.Title>
                <Modal.Description>{description}</Modal.Description>
              </div>
            </div>

            {/* Search bar and Add Files button */}
            <div className="flex items-center gap-2 px-2">
              <InputTypeIn
                ref={searchInputRef}
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
          </Modal.Header>

          <Modal.Body className="flex flex-col flex-1 min-h-0 overflow-auto bg-background-tint-01">
            {filtered.length === 0 ? (
              <div className="p-4 flex w-full h-full items-center justify-center">
                <Text text03>No files found</Text>
              </div>
            ) : (
              <ScrollIndicatorDiv variant="shadow" className="px-2 pt-2 gap-2">
                {filtered.map((projectFile) => {
                  const isSelected = selectedIds.has(projectFile.id);
                  return (
                    <FileAttachment
                      key={projectFile.id}
                      file={projectFile}
                      isSelected={isSelected}
                      onClick={
                        onPickRecent
                          ? () => {
                              if (isSelected) {
                                onUnpickRecent?.(projectFile);
                                setSelectedIds((prev) => {
                                  const next = new Set(prev);
                                  next.delete(projectFile.id);
                                  return next;
                                });
                              } else {
                                onPickRecent(projectFile);
                                setSelectedIds((prev) => {
                                  const next = new Set(prev);
                                  next.add(projectFile.id);
                                  return next;
                                });
                              }
                            }
                          : undefined
                      }
                      onView={onView ? () => onView(projectFile) : undefined}
                      onDelete={
                        onDelete ? () => onDelete(projectFile) : undefined
                      }
                    />
                  );
                })}
              </ScrollIndicatorDiv>
            )}
          </Modal.Body>

          <Modal.Footer className="flex items-center justify-between p-4 border-t">
            {/* Left side: file count and controls */}
            <div className="flex items-center gap-2">
              <Text text03>
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

            {/* Right side: Done button */}
            <Button secondary onClick={() => onOpenChange(false)}>
              Done
            </Button>
          </Modal.Footer>
        </Modal.Content>
      </Modal>
    </>
  );
}
