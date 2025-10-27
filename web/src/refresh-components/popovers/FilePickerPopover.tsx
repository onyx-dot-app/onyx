"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  Popover,
  PopoverContent,
  PopoverMenu,
  PopoverTrigger,
} from "@/components/ui/popover";
import { cn, noProp } from "@/lib/utils";
import CoreModal from "@/refresh-components/modals/CoreModal";
import UserFilesModalContent from "@/components/modals/UserFilesModalContent";
import {
  ProjectFile,
  UserFileStatus,
} from "@/app/chat/projects/projectsService";
import LineItem from "@/refresh-components/buttons/LineItem";
import SvgPaperclip from "@/icons/paperclip";
import SvgFiles from "@/icons/files";
import MoreHorizontal from "@/icons/more-horizontal";
import SvgFileText from "@/icons/file-text";
import SvgExternalLink from "@/icons/external-link";
import IconButton from "@/refresh-components/buttons/IconButton";
import { usePopup } from "@/components/admin/connectors/Popup";
import { useProjectsContext } from "@/app/chat/projects/ProjectsContext";
import Text from "@/refresh-components/texts/Text";
import { MAX_FILES_TO_SHOW } from "@/lib/constants";
import SvgLoader from "@/icons/loader";

const getFileExtension = (fileName: string): string => {
  const idx = fileName.lastIndexOf(".");
  if (idx === -1) return "";
  const ext = fileName.slice(idx + 1).toLowerCase();
  if (ext === "txt") return "PLAINTEXT";
  return ext.toUpperCase();
};

interface FileLineItemProps {
  projectFile: ProjectFile;
  onPickRecent: (file: ProjectFile) => void;
  onFileClick: (file: ProjectFile) => void;
}

function FileLineItem({
  projectFile,
  onPickRecent,
  onFileClick,
}: FileLineItemProps) {
  const showLoader = useMemo(
    () =>
      String(projectFile.status) === UserFileStatus.PROCESSING ||
      String(projectFile.status) === UserFileStatus.UPLOADING ||
      String(projectFile.status) === UserFileStatus.DELETING,
    [projectFile.status]
  );

  const disableActionButton = useMemo(
    () =>
      String(projectFile.status) === UserFileStatus.UPLOADING ||
      String(projectFile.status) === UserFileStatus.DELETING,
    [projectFile.status]
  );

  return (
    <LineItem
      key={projectFile.id}
      onClick={noProp(() => onPickRecent(projectFile))}
      icon={
        showLoader
          ? ({ className }) => (
              <SvgLoader className={cn(className, "animate-spin")} />
            )
          : SvgFileText
      }
      rightChildren={
        <div className="h-[1rem] flex flex-col justify-center">
          <IconButton
            icon={SvgExternalLink}
            onClick={noProp(() => onFileClick(projectFile))}
            tooltip="View File"
            disabled={disableActionButton}
            internal
            className="hidden group-hover/LineItem:flex"
          />
          <Text
            className="flex group-hover/LineItem:hidden"
            secondaryBody
            text03
          >
            {getFileExtension(projectFile.name)}
          </Text>
        </div>
      }
    >
      {projectFile.name}
    </LineItem>
  );
}

interface FilePickerPopoverContentsProps {
  recentFiles: ProjectFile[];
  onPickRecent: (file: ProjectFile) => void;
  onFileClick: (file: ProjectFile) => void;
  triggerUploadPicker: () => void;
  setShowRecentFiles: (show: boolean) => void;
}

function FilePickerPopoverContents({
  recentFiles,
  onPickRecent,
  onFileClick,
  triggerUploadPicker,
  setShowRecentFiles,
}: FilePickerPopoverContentsProps) {
  // These are the "quick" files that we show. Essentially "speed dial", but for files.
  // The rest of the files will be hidden behind the "All Recent Files" button, should there be more files left to show!
  const hasFiles = recentFiles.length > 0;
  const shouldShowMoreFilesButton = recentFiles.length > MAX_FILES_TO_SHOW;
  const quickAccessFiles = recentFiles.slice(0, MAX_FILES_TO_SHOW);

  return (
    <PopoverMenu className="w-[15.5rem] max-h-[300px] border-transparent">
      {[
        // Action button to upload more files
        <LineItem
          key="upload-files"
          icon={SvgPaperclip}
          description="Upload a file from your device"
          onClick={triggerUploadPicker}
        >
          Upload Files
        </LineItem>,

        // Separator
        null,

        // Title
        hasFiles && (
          <div key="recent-files" className="pt-1">
            <Text text02 secondaryBody className="py-1 px-3">
              Recent Files
            </Text>
          </div>
        ),

        // Quick access files
        ...quickAccessFiles.map((projectFile) => (
          <FileLineItem
            key={projectFile.id}
            projectFile={projectFile}
            onPickRecent={onPickRecent}
            onFileClick={onFileClick}
          />
        )),

        // Rest of the files
        shouldShowMoreFilesButton && (
          <LineItem
            icon={MoreHorizontal}
            onClick={() => setShowRecentFiles(true)}
          >
            All Recent Files
          </LineItem>
        ),
      ]}
    </PopoverMenu>
  );
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
  const { allRecentFiles } = useProjectsContext();
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [showRecentFiles, setShowRecentFiles] = useState(false);
  const [open, setOpen] = useState(false);
  // Snapshot of recent files to avoid re-arranging when the modal is open
  const [recentFilesSnapshot, setRecentFilesSnapshot] = useState<ProjectFile[]>(
    []
  );
  const { popup, setPopup } = usePopup();
  const { deleteUserFile, setCurrentMessageFiles } = useProjectsContext();
  const [deletedFileIds, setDeletedFileIds] = useState<string[]>([]);

  const triggerUploadPicker = () => fileInputRef.current?.click();

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
          setPopup({
            message: "File deleted successfully",
            type: "success",
          });
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
          let projects = result.project_names.join(", ");
          let assistants = result.assistant_names.join(", ");
          let message = "Cannot delete file. It is associated with";
          if (projects) {
            message += ` projects: ${projects}`;
          }
          if (projects && assistants) {
            message += " and ";
          }
          if (assistants) {
            message += `assistants: ${assistants}`;
          }

          setPopup({
            message: message,
            type: "error",
          });
        }
      })
      .catch((error) => {
        // Revert status and show error if the delete request fails
        setRecentFilesSnapshot((prev) =>
          prev.map((f) => (f.id === file.id ? { ...f, status: lastStatus } : f))
        );
        setPopup({
          message: "Failed to delete file. Please try again.",
          type: "error",
        });
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

      <div className={cn("relative")}>
        {popup}
        <Popover open={open} onOpenChange={setOpen}>
          <PopoverTrigger asChild>
            {typeof trigger === "function" ? trigger(open) : trigger}
          </PopoverTrigger>
          <PopoverContent align="start" side="bottom">
            <FilePickerPopoverContents
              recentFiles={recentFilesSnapshot}
              onPickRecent={(file) => {
                onPickRecent && onPickRecent(file);
                setOpen(false);
              }}
              onFileClick={(file) => {
                onFileClick && onFileClick(file);
                setOpen(false);
              }}
              triggerUploadPicker={() => {
                triggerUploadPicker();
                setOpen(false);
              }}
              setShowRecentFiles={(show) => {
                setShowRecentFiles(show);
                // Close the small popover when opening the dialog
                if (show) setOpen(false);
              }}
            />
          </PopoverContent>
        </Popover>

        {showRecentFiles && (
          <CoreModal
            className="w-[32rem] border flex flex-col bg-background-tint-00"
            onClickOutside={() => setShowRecentFiles(false)}
          >
            <UserFilesModalContent
              title="Recent Files"
              description="Upload files or pick from your recent files."
              icon={SvgFiles}
              recentFiles={recentFilesSnapshot}
              onPickRecent={(file) => {
                onPickRecent && onPickRecent(file);
              }}
              onUnpickRecent={(file) => {
                onUnpickRecent && onUnpickRecent(file);
              }}
              handleUploadChange={handleUploadChange}
              onView={onFileClick}
              onClose={() => setShowRecentFiles(false)}
              selectedFileIds={selectedFileIds}
              onDelete={handleDeleteFile}
            />
          </CoreModal>
        )}
      </div>
    </>
  );
}
