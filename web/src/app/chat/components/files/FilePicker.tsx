"use client";

import React, { useRef, useState } from "react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import CoreModal from "@/refresh-components/modals/CoreModal";
import UserFilesModalContent from "@/components/modals/UserFilesModalContent";
import { ProjectFile } from "../../projects/projectsService";
import LineItem from "@/refresh-components/buttons/LineItem";
import SvgPaperclip from "@/icons/paperclip";
import SvgFiles from "@/icons/files";
import MoreHorizontal from "@/icons/more-horizontal";
import SvgFileText from "@/icons/file-text";
import SvgExternalLink from "@/icons/external-link";
import IconButton from "@/refresh-components/buttons/IconButton";
import Text from "@/refresh-components/Text";

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
                    {String(f.status).toLowerCase() === "processing" ? (
                      <Loader2 className="h-4 w-4 animate-spin text-text-02" />
                    ) : (
                      <SvgFileText className="h-4 w-4 stroke-text-02" />
                    )}
                  </div>
                  <Text
                    text03
                    mainUiBody
                    nowrap
                    className="truncate max-w-[160px]"
                  >
                    {f.name}
                  </Text>

                  <div className="relative flex items-center ml-auto mr-2">
                    <Text
                      text02
                      secondaryBody
                      className="p-0.5 group-hover:opacity-0 transition-opacity duration-150"
                    >
                      {getFileExtension(f.name)}
                    </Text>

                    {onFileClick &&
                      String(f.status).toLowerCase() !== "processing" && (
                        <IconButton
                          internal
                          icon={SvgExternalLink}
                          tooltip="View file"
                          className="absolute flex items-center justify-center opacity-0 group-hover:opacity-100 focus:opacity-100 transition-opacity duration-150 p-0 bg-transparent hover:bg-transparent"
                          onClick={(e) => {
                            e.stopPropagation();
                            e.preventDefault();
                            onFileClick(f);
                          }}
                        />
                      )}
                  </div>
                </Row>
              </div>
            </div>
          ))}

          {recentFiles.length > 3 && (
            <button
              type="button"
              onClick={() => setShowRecentFiles(true)}
              className="w-full rounded-lg hover:bg-background-neutral-02 hover:text-neutral-900 dark:hover:text-neutral-50"
            >
              <div className="flex items-center w-full m-1 p-1">
                <Row>
                  <div className="p-0.5">
                    <MoreHorizontal className="h-4 w-4 stroke-text-02" />
                  </div>
                  <Text text03 mainUiBody>
                    All Recent Files
                  </Text>
                </Row>
              </div>
            </button>
          )}

          <div className="border-b" />
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
  const [recentFilesSnapshot, setRecentFilesSnapshot] = useState<
    ProjectFile[] | null
  >(null);
  // Buffer selection changes made within the modal until close
  const [modalInitialSelectedIds, setModalInitialSelectedIds] =
    useState<Set<string> | null>(null);
  const [modalSelectedIds, setModalSelectedIds] = useState<Set<string> | null>(
    null
  );
  // Track files to hide from the quick popover (recent top 3) once added
  const [hiddenQuickIds, setHiddenQuickIds] = useState<Set<string>>(
    new Set(selectedFileIds || [])
  );

  // Keep quick-popover hidden set in sync with externally selected ids
  React.useEffect(() => {
    // Merge externally selected ids into the hidden set (do not clobber optimistic hides)
    setHiddenQuickIds((prev) => {
      const next = new Set(prev);
      (selectedFileIds || []).forEach((id) => next.add(id));
      return next;
    });
  }, [selectedFileIds]);

  const triggerUploadPicker = () => fileInputRef.current?.click();

  const getFilesLookup = () => {
    const source = recentFilesSnapshot ?? recentFiles;
    const byId = new Map<string, ProjectFile>();
    source.forEach((f) => byId.set(f.id, f));
    return byId;
  };

  const commitModalSelection = () => {
    const initial = modalInitialSelectedIds ?? new Set(selectedFileIds || []);
    const current = modalSelectedIds ?? new Set(initial);

    const toAdd: string[] = [];
    const toRemove: string[] = [];

    current.forEach((id) => {
      if (!initial.has(id)) toAdd.push(id);
    });
    initial.forEach((id) => {
      if (!current.has(id)) toRemove.push(id);
    });

    const byId = getFilesLookup();
    toAdd.forEach((id) => {
      const f = byId.get(id);
      if (f && onPickRecent) onPickRecent(f);
    });
    toRemove.forEach((id) => {
      const f = byId.get(id);
      if (f && onUnpickRecent) onUnpickRecent(f);
    });

    // Optimistically sync quick-popover visibility with committed changes
    if (toAdd.length > 0 || toRemove.length > 0) {
      setHiddenQuickIds((prev) => {
        const next = new Set(prev);
        for (const id of toAdd) next.add(id);
        for (const id of toRemove) next.delete(id);
        return next;
      });
    }

    // Clear modal buffers
    setModalInitialSelectedIds(null);
    setModalSelectedIds(null);
    setRecentFilesSnapshot(null);
  };

  return (
    <div className={cn("relative", className)}>
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
            key={`quick-${Array.from(hiddenQuickIds).join("-")}`}
            recentFiles={recentFiles.filter((f) => !hiddenQuickIds.has(f.id))}
            onPickRecent={(file) => {
              onPickRecent && onPickRecent(file);
              // Hide immediately from quick popover on next open
              setHiddenQuickIds((prev) => {
                const next = new Set(prev);
                next.add(file.id);
                return next;
              });
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
              if (show) {
                setRecentFilesSnapshot(recentFiles.slice());
                const initial = new Set<string>(selectedFileIds || []);
                setModalInitialSelectedIds(initial);
                setModalSelectedIds(new Set(initial));
              } else {
                setRecentFilesSnapshot(null);
                setModalInitialSelectedIds(null);
                setModalSelectedIds(null);
              }
              // Close the small popover when opening the dialog
              if (show) setOpen(false);
            }}
          />
        </PopoverContent>
      </Popover>

      {showRecentFiles && (
        <CoreModal
          className="w-[48rem] min-w-[48rem] max-w-[48rem] overflow-hidden"
          onClickOutside={() => {
            commitModalSelection();
            setShowRecentFiles(false);
          }}
        >
          <UserFilesModalContent
            title="Recent Files"
            description="Upload files or pick from your recent files."
            icon={SvgFiles}
            recentFiles={recentFilesSnapshot ?? recentFiles}
            fixedHeight={588}
            onPickRecent={(file) => {
              setModalSelectedIds((prev) => {
                const next = new Set(prev ?? modalInitialSelectedIds ?? []);
                next.add(file.id);
                return next;
              });
            }}
            onUnpickRecent={(file) => {
              setModalSelectedIds((prev) => {
                const next = new Set(prev ?? modalInitialSelectedIds ?? []);
                next.delete(file.id);
                return next;
              });
            }}
            handleUploadChange={handleUploadChange}
            onFileClick={onFileClick}
            onClose={() => {
              commitModalSelection();
              setShowRecentFiles(false);
            }}
            selectedFileIds={
              modalSelectedIds ? Array.from(modalSelectedIds) : selectedFileIds
            }
          />
        </CoreModal>
      )}
    </div>
  );
}
