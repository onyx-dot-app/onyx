"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import {
  Button,
  Dropdown,
  LineItemButton,
  useCreateModal,
  type DropdownMenuItem,
  type DropdownMenuRow,
  type DropdownRowProps,
} from "@opal/components";
import { noProp } from "@/lib/utils";
import { cn } from "@opal/utils";
import UserFilesModal from "@/sections/modals/UserFilesModal";
import { ProjectFile, UserFileStatus } from "@/lib/projects/types";
import { isFilePending } from "@/lib/projects/utils";
import { Hoverable } from "@opal/core";
import { toast } from "@opal/layouts";
import { useProjectsContext } from "@/lib/projects/providers";
import Text from "@/refresh-components/texts/Text";
import { MAX_FILES_TO_SHOW } from "@/lib/constants";
import { isImageFile } from "@/lib/utils";
import {
  SvgExternalLink,
  SvgFileText,
  SvgImage,
  SvgLoader,
  SvgMoreHorizontal,
  SvgUploadSquare,
} from "@opal/icons";
const getFileExtension = (fileName: string): string => {
  const idx = fileName.lastIndexOf(".");
  if (idx === -1) return "";
  const ext = fileName.slice(idx + 1).toLowerCase();
  if (ext === "txt") return "PLAINTEXT";
  return ext.toUpperCase();
};

interface FileLineItemProps {
  projectFile: ProjectFile;
  highlighted: boolean;
  /** The row props from the list: the id, role, stop and click handling. */
  rowProps: DropdownRowProps;
  onFileClick: (file: ProjectFile) => void;
}

/** A recent file: a presentational row whose end control views the file. */
function FileLineItem({
  projectFile,
  highlighted,
  rowProps,
  onFileClick,
}: FileLineItemProps) {
  const t = useTranslations("common.filePicker");
  const showLoader = useMemo(
    () =>
      isFilePending(projectFile.status) ||
      projectFile.status === UserFileStatus.DELETING,
    [projectFile.status]
  );

  const disableActionButton = useMemo(
    () =>
      String(projectFile.status) === UserFileStatus.UPLOADING ||
      String(projectFile.status) === UserFileStatus.DELETING,
    [projectFile.status]
  );

  return (
    <Hoverable.Root group="FileLineItem">
      <LineItemButton
        presentational
        selectVariant="select-heavy"
        interaction={highlighted ? "hover" : "rest"}
        sizePreset="main-ui"
        rounding={2}
        icon={
          showLoader
            ? ({ className }) => (
                <SvgLoader className={cn(className, "animate-spin")} />
              )
            : isImageFile(projectFile.name)
              ? SvgImage
              : SvgFileText
        }
        rightChildren={
          <div className="h-4 flex flex-col justify-center">
            <Hoverable.Item
              group="FileLineItem"
              variant="replace-on-hover"
              resting={
                <Text as="p" secondaryBody text03>
                  {getFileExtension(projectFile.name)}
                </Text>
              }
            >
              <Button
                icon={SvgExternalLink}
                onClick={noProp(() => onFileClick(projectFile))}
                tooltip={t("viewFileButton.tooltip")}
                disabled={disableActionButton}
                prominence="internal"
                size="sm"
              />
            </Hoverable.Item>
          </div>
        }
        title={projectFile.name}
        {...rowProps}
      />
    </Hoverable.Root>
  );
}

interface FilePickerItemsProps {
  recentFiles: ProjectFile[];
  onPickRecent: (file: ProjectFile) => void;
  onFileClick: (file: ProjectFile) => void;
  triggerUploadPicker: () => void;
  openRecentFilesModal: () => void;
}

/**
 * The rows: upload, then the "quick" recent files (speed dial, for files)
 * under a title, and a row to the rest when there are more.
 */
function useFilePickerItems({
  recentFiles,
  onPickRecent,
  onFileClick,
  triggerUploadPicker,
  openRecentFilesModal,
}: FilePickerItemsProps): DropdownMenuItem[] {
  const t = useTranslations("common.filePicker");
  const hasFiles = recentFiles.length > 0;
  const shouldShowMoreFilesButton = recentFiles.length > MAX_FILES_TO_SHOW;
  const quickAccessFiles = recentFiles.slice(0, MAX_FILES_TO_SHOW);

  const fileRows: DropdownMenuRow[] = [
    ...quickAccessFiles.map(
      (projectFile): DropdownMenuRow => ({
        kind: "custom",
        id: `file-${projectFile.id}`,
        keywords: [projectFile.name],
        onActivate: () => onPickRecent(projectFile),
        // ArrowRight reaches the row's view control.
        onSecondary: () => onFileClick(projectFile),
        render: ({ highlighted, props }) => (
          <FileLineItem
            projectFile={projectFile}
            highlighted={highlighted}
            rowProps={props}
            onFileClick={onFileClick}
          />
        ),
      })
    ),
    ...(shouldShowMoreFilesButton
      ? [
          {
            kind: "action" as const,
            id: "more-files",
            icon: SvgMoreHorizontal,
            title: t("allRecentFilesButton.title"),
            onSelect: openRecentFilesModal,
          },
        ]
      : []),
  ];

  return [
    {
      kind: "action",
      id: "upload-files",
      icon: SvgUploadSquare,
      title: t("uploadFiles.title"),
      description: t("uploadFiles.description"),
      onSelect: triggerUploadPicker,
    },
    ...(hasFiles
      ? [
          {
            kind: "group" as const,
            title: t("recentFiles.title"),
            items: fileRows,
          },
        ]
      : []),
  ];
}

export interface FilePickerPopoverProps {
  onPickRecent?: (file: ProjectFile) => void;
  onUnpickRecent?: (file: ProjectFile) => void;
  onFileClick?: (file: ProjectFile) => void;
  handleUploadChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  trigger?: React.ReactNode | ((open: boolean) => React.ReactNode);
  selectedFileIds?: string[];
}

export default function FilePickerPopover({
  onPickRecent,
  onUnpickRecent,
  onFileClick,
  handleUploadChange,
  trigger,
  selectedFileIds,
}: FilePickerPopoverProps) {
  const t = useTranslations("common.filePicker");
  const { allRecentFiles } = useProjectsContext();
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const recentFilesModal = useCreateModal();
  const [open, setOpen] = useState(false);
  // Snapshot of recent files to avoid re-arranging when the modal is open
  const [recentFilesSnapshot, setRecentFilesSnapshot] = useState<ProjectFile[]>(
    []
  );
  const { deleteUserFile, setCurrentMessageFiles } = useProjectsContext();
  const [deletedFileIds, setDeletedFileIds] = useState<string[]>([]);

  const triggerUploadPicker = () => fileInputRef.current?.click();
  // Every pick closes the list; the view control closes it too.
  const items = useFilePickerItems({
    recentFiles: recentFilesSnapshot,
    onPickRecent: (file) => onPickRecent?.(file),
    onFileClick: (file) => {
      onFileClick?.(file);
      setOpen(false);
    },
    triggerUploadPicker,
    openRecentFilesModal: () => recentFilesModal.toggle(true),
  });

  useEffect(() => {
    setRecentFilesSnapshot(
      allRecentFiles.slice().filter((f) => !deletedFileIds.includes(f.id))
    );
  }, [allRecentFiles]);

  const handleDeleteFile = (file: ProjectFile) => {
    const lastStatus = file.status;
    setRecentFilesSnapshot((prev) =>
      prev.map((f) =>
        f.id === file.id ? { ...f, status: UserFileStatus.DELETING } : f
      )
    );
    deleteUserFile(file.id)
      .then((result) => {
        if (!result.has_associations) {
          toast.success(t("toasts.deleteSuccess"));
          setCurrentMessageFiles((prev) =>
            prev.filter((f) => f.id !== file.id)
          );
          setDeletedFileIds((prev) => [...prev, file.id]);
          setRecentFilesSnapshot((prev) => prev.filter((f) => f.id != file.id));
        } else {
          setRecentFilesSnapshot((prev) =>
            prev.map((f) =>
              f.id === file.id ? { ...f, status: lastStatus } : f
            )
          );
          const projects = result.project_names.join(", ");
          const assistants = result.assistant_names.join(", ");
          const message =
            projects && assistants
              ? t("toasts.associatedBoth", { projects, assistants })
              : projects
                ? t("toasts.associatedProjects", { projects })
                : t("toasts.associatedAssistants", { assistants });

          toast.error(message);
        }
      })
      .catch((error) => {
        // Revert status and show error if the delete request fails
        setRecentFilesSnapshot((prev) =>
          prev.map((f) => (f.id === file.id ? { ...f, status: lastStatus } : f))
        );
        toast.error(t("toasts.deleteFailed"));
        // Useful for debugging; safe in client components
        console.error("Failed to delete file", error);
      });
  };

  return (
    <>
      <input
        ref={fileInputRef}
        type="file"
        className="hidden"
        multiple
        onChange={handleUploadChange}
        accept={"*/*"}
      />

      <recentFilesModal.Provider>
        <UserFilesModal
          title={t("recentFiles.title")}
          description={t("recentFilesModal.description")}
          recentFiles={recentFilesSnapshot}
          onPickRecent={(file) => {
            onPickRecent?.(file);
          }}
          onUnpickRecent={(file) => {
            onUnpickRecent?.(file);
          }}
          handleUploadChange={handleUploadChange}
          onView={onFileClick}
          selectedFileIds={selectedFileIds}
          onDelete={handleDeleteFile}
        />
      </recentFilesModal.Provider>

      <Dropdown width={20} open={open} onOpenChange={setOpen}>
        <Dropdown.Trigger asChild>
          {typeof trigger === "function" ? trigger(open) : trigger}
        </Dropdown.Trigger>
        <Dropdown.Data label={t("uploadFiles.title")} items={items} />
      </Dropdown>
    </>
  );
}
