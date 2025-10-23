"use client";

import React, { useEffect, useRef, useState } from "react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import CoreModal from "@/refresh-components/modals/CoreModal";
import UserFilesModalContent from "@/components/modals/UserFilesModalContent";
import { ProjectFile, UserFileStatus } from "../../projects/projectsService";
import LineItem from "@/refresh-components/buttons/LineItem";
import SvgPaperclip from "@/icons/paperclip";
import SvgFiles from "@/icons/files";
import MoreHorizontal from "@/icons/more-horizontal";
import SvgFileText from "@/icons/file-text";
import SvgExternalLink from "@/icons/external-link";
import SvgTrash from "@/icons/trash";
import IconButton from "@/refresh-components/buttons/IconButton";
import { usePopup } from "@/components/admin/connectors/Popup";
import { useProjectsContext } from "@/app/chat/projects/ProjectsContext";
import Text from "@/refresh-components/texts/Text";
import Button from "@/refresh-components/buttons/Button";

// Small helper to render an icon + label row
const Row = ({ children }: { children: React.ReactNode }) => (
  <div className="flex items-center gap-2 w-full">{children}</div>
);

interface FilePickerContentsProps {
  recentFiles: ProjectFile[];
  onPickRecent?: (file: ProjectFile) => void;
  onFileClick?: (file: ProjectFile) => void;
  triggerUploadPicker: () => void;
  setShowRecentFiles: (show: boolean) => void;
  onDelete?: (file: ProjectFile) => void;
}

const getFileExtension = (fileName: string): string => {
  const idx = fileName.lastIndexOf(".");
  if (idx === -1) return "";
  const ext = fileName.slice(idx + 1).toLowerCase();
  if (ext === "txt") return "PLAINTEXT";
  return ext.toUpperCase();
};

export function FilePickerContents({
  recentFiles,
  onPickRecent,
  onFileClick,
  triggerUploadPicker,
  setShowRecentFiles,
  onDelete,
}: FilePickerContentsProps) {
  return (
    <>
      {recentFiles.length > 0 && (
        <>
          <Text text02 secondaryBody className="mx-2 mt-2 mb-1">
            Recent Files
          </Text>

          {recentFiles.slice(0, 3).map((f) => (
            <div
              role="button"
              tabIndex={0}
              key={f.id}
              onClick={(e) => {
                e.stopPropagation();
                e.preventDefault();
                onPickRecent && onPickRecent(f);
              }}
              className="w-full rounded-lg hover:bg-background-neutral-02 group p-0.5"
            >
              <div className="flex items-center w-full m-1 mt-1 p-0.5 group">
                <Row>
                  <div className="p-0.5">
                    {String(f.status) === UserFileStatus.PROCESSING ||
                    String(f.status) === UserFileStatus.UPLOADING ||
                    String(f.status) === UserFileStatus.DELETING ? (
                      <Loader2 className="h-4 w-4 animate-spin text-text-02" />
                    ) : (
                      <SvgFileText className="h-4 w-4 stroke-text-02" />
                    )}
                  </div>
                  <div className="flex items-center gap-1 min-w-0">
                    <Text
                      text03
                      mainUiBody
                      nowrap
                      className="truncate max-w-[160px]"
                    >
                      {f.name}
                    </Text>
                    {onFileClick &&
                      String(f.status) !== UserFileStatus.PROCESSING &&
                      String(f.status) !== UserFileStatus.UPLOADING &&
                      String(f.status) !== UserFileStatus.DELETING && (
                        <IconButton
                          internal
                          icon={SvgExternalLink}
                          tooltip="View file"
                          className="opacity-0 group-hover:opacity-100 focus:opacity-100 transition-opacity duration-150 p-0 bg-transparent hover:bg-transparent"
                          onClick={(e) => {
                            e.stopPropagation();
                            e.preventDefault();
                            onFileClick(f);
                          }}
                        />
                      )}
                  </div>

                  <div className="relative flex items-center ml-auto mr-2">
                    <Text
                      text02
                      secondaryBody
                      className="p-0.5 group-hover:opacity-0 transition-opacity duration-150"
                    >
                      {getFileExtension(f.name)}
                    </Text>

                    {onDelete &&
                      String(f.status) !== UserFileStatus.UPLOADING &&
                      String(f.status) !== UserFileStatus.DELETING && (
                        <IconButton
                          internal
                          icon={SvgTrash}
                          tooltip="Delete file"
                          className="absolute flex items-center justify-center opacity-0 group-hover:opacity-100 focus:opacity-100 transition-opacity duration-150 p-0 bg-transparent hover:bg-transparent"
                          onClick={(e) => {
                            e.stopPropagation();
                            e.preventDefault();
                            onDelete(f);
                          }}
                        />
                      )}
                  </div>
                </Row>
              </div>
            </div>
          ))}

          {recentFiles.length > 3 && (
            <LineItem
              icon={MoreHorizontal}
              onClick={() => setShowRecentFiles(true)}
            >
              <Text text03 mainUiBody>
                All Recent Files
              </Text>
            </LineItem>
          )}

          <div className="border-b my-0.5" />
        </>
      )}

      <LineItem
        icon={SvgPaperclip}
        description="Upload a file from your device"
        onClick={triggerUploadPicker}
      >
        Upload Files
      </LineItem>
    </>
  );
}

interface FilePickerProps {
  className?: string;
  onPickRecent?: (file: ProjectFile) => void;
  onUnpickRecent?: (file: ProjectFile) => void;
  onFileClick?: (file: ProjectFile) => void;
  recentFiles: ProjectFile[];
  handleUploadChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  trigger?: React.ReactNode;
  selectedFileIds?: string[];
}

export default function FilePicker({
  className,
  onPickRecent,
  onUnpickRecent,
  onFileClick,
  recentFiles,
  handleUploadChange,
  trigger,
  selectedFileIds,
}: FilePickerProps) {
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
      recentFiles.slice().filter((f) => !deletedFileIds.includes(f.id))
    );
  }, [recentFiles]);

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
    <div className={cn("relative", className)}>
      {popup}
      <input
        ref={fileInputRef}
        type="file"
        className="hidden"
        multiple
        onChange={handleUploadChange}
        accept={"*/*"}
      />
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <div className="relative cursor-pointer flex items-center group rounded-lg text-input-text px-0 h-8">
            {trigger}
          </div>
        </PopoverTrigger>
        <PopoverContent
          align="start"
          sideOffset={6}
          className="w-[15.5rem] max-h-[300px] border-transparent"
          side="top"
        >
          <FilePickerContents
            recentFiles={recentFilesSnapshot}
            onPickRecent={(file) => {
              onPickRecent && onPickRecent(file);
              setOpen(false);
            }}
            onFileClick={(file) => {
              onFileClick && onFileClick(file);
              setOpen(false);
            }}
            onDelete={handleDeleteFile}
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
          className="w-[32rem] rounded-16 border flex flex-col bg-background-tint-00"
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
            onFileClick={onFileClick}
            onClose={() => setShowRecentFiles(false)}
            selectedFileIds={selectedFileIds}
            showRemove
            onRemove={handleDeleteFile}
          />
        </CoreModal>
      )}
    </div>
  );
}
