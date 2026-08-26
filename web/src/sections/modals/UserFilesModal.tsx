"use client";

import React, { useRef, useState, useEffect, useMemo } from "react";
import { InputTypeIn } from "@opal/components";
import { ProjectFile } from "@/lib/projects/providers";
import Text from "@/refresh-components/texts/Text";
import type { IconProps } from "@opal/types";
import { getFileExtension, isImageExtension } from "@/lib/utils";
import { UserFileStatus } from "@/lib/projects/types";
import AttachmentButton from "@/refresh-components/buttons/AttachmentButton";
import { Modal } from "@opal/components";
import { useModal } from "@opal/components";
import TextSeparator from "@/refresh-components/TextSeparator";
import {
  SvgEye,
  SvgFiles,
  SvgFileText,
  SvgImage,
  SvgPlusCircle,
  SvgTrash,
  SvgXCircle,
  SvgSimpleLoader,
} from "@opal/icons";
import { Section } from "@/layouts/general-layouts";
import useFilter from "@/hooks/useFilter";
import { Button } from "@opal/components";
import ScrollIndicatorDiv from "@/refresh-components/ScrollIndicatorDiv";
import { timeAgo } from "@opal/time";
import { useTranslations } from "next-intl";

function getIcon(
  file: ProjectFile,
  isProcessing: boolean
): React.FunctionComponent<IconProps> {
  if (isProcessing) return SvgSimpleLoader;
  const ext = getFileExtension(file.name).toLowerCase();
  if (isImageExtension(ext)) return SvgImage;
  return SvgFileText;
}

// Translated labels for the in-progress statuses; the rest fall back to the
// file's own extension or raw status, which are data rather than copy.
interface FileStatusLabels {
  processing: string;
  uploading: string;
  deleting: string;
}

function getDescription(file: ProjectFile, labels: FileStatusLabels): string {
  const s = String(file.status || "");
  const typeLabel = getFileExtension(file.name);
  if (s === UserFileStatus.PROCESSING) return labels.processing;
  if (s === UserFileStatus.UPLOADING) return labels.uploading;
  if (s === UserFileStatus.DELETING) return labels.deleting;
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
  const t = useTranslations("chat.modals.userFiles");
  const isProcessing =
    String(file.status) === UserFileStatus.PROCESSING ||
    String(file.status) === UserFileStatus.UPLOADING ||
    String(file.status) === UserFileStatus.DELETING;

  const Icon = getIcon(file, isProcessing);
  const description = getDescription(file, {
    processing: t("fileStatus.processing.label"),
    uploading: t("fileStatus.uploading.label"),
    deleting: t("fileStatus.deleting.label"),
  });
  const rightText = file.last_accessed_at
    ? (timeAgo(file.last_accessed_at) ?? "")
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
  const t = useTranslations("chat.modals.userFiles");
  const { isOpen, toggle } = useModal();
  const [selectedIds, setSelectedIds] = useState<Set<string>>(
    () => new Set(selectedFileIds || [])
  );
  const [showOnlySelected, setShowOnlySelected] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const searchInputRef = useRef<HTMLInputElement | null>(null);
  const triggerUploadPicker = () => fileInputRef.current?.click();

  useEffect(() => {
    if (selectedFileIds) setSelectedIds(new Set(selectedFileIds));
    else setSelectedIds(new Set());
  }, [selectedFileIds]);

  const selectedCount = selectedIds.size;

  function handleDeselectAll() {
    selectedIds.forEach((id) => {
      const file = recentFiles.find((f) => f.id === id);
      if (file) {
        onUnpickRecent?.(file);
      }
    });
    setSelectedIds(new Set());
  }

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
          width="sm"
          height="lg"
          onOpenAutoFocus={(e) => {
            e.preventDefault();
            searchInputRef.current?.focus();
          }}
          preventAccidentalClose={false}
        >
          <Modal.Header icon={SvgFiles} title={title} description={description}>
            {/* Search bar section */}
            <Section flexDirection="row" gap={2}>
              <InputTypeIn
                ref={searchInputRef}
                placeholder={t("searchInput.placeholder")}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                searchIcon
                autoComplete="off"
                tabIndex={0}
                onFocus={(e) => {
                  e.target.select();
                }}
              />
              {handleUploadChange && (
                <Button
                  icon={SvgPlusCircle}
                  prominence="internal"
                  onClick={triggerUploadPicker}
                >
                  {t("addFilesButton.label")}
                </Button>
              )}
            </Section>
          </Modal.Header>

          <Modal.Body
            padding={filtered.length === 0 ? 2 : 0}
            gap={2}
            alignItems="center"
          >
            {/* File display section */}
            {filtered.length === 0 ? (
              <Text text03>{t("emptyState.description")}</Text>
            ) : (
              <ScrollIndicatorDiv className="p-2 gap-2 max-h-[70vh]">
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
                  <TextSeparator
                    text={t("fileCount.label", { count: recentFiles.length })}
                  />
                )}
              </ScrollIndicatorDiv>
            )}
          </Modal.Body>

          <Modal.Footer>
            {/* Left side: file count and controls */}
            {onPickRecent && (
              <Section flexDirection="row" justifyContent="start" gap={2}>
                <Text as="p" text03>
                  {t("selectedCount.label", { count: selectedCount })}
                </Text>
                <Button
                  icon={SvgEye}
                  prominence="tertiary"
                  size="sm"
                  onClick={() => setShowOnlySelected(!showOnlySelected)}
                  interaction={showOnlySelected ? "hover" : "rest"}
                />
                <Button
                  disabled={selectedCount === 0}
                  icon={SvgXCircle}
                  prominence="tertiary"
                  size="sm"
                  onClick={handleDeselectAll}
                />
              </Section>
            )}

            {/* Right side: Done button */}
            <Button prominence="secondary" onClick={() => toggle(false)}>
              {t("doneButton.label")}
            </Button>
          </Modal.Footer>
        </Modal.Content>
      </Modal>
    </>
  );
}
