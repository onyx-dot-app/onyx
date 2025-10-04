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
            <button
              type="button"
              key={f.id}
              onClick={() =>
                onPickRecent ? onPickRecent(f) : console.log("Picked recent", f)
              }
              className="w-full rounded-lg hover:bg-background-neutral-02 group"
            >
              <div className="flex items-center w-full m-1 mt-2 p-0.5 group">
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
                    mainBody
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
                            onFileClick && onFileClick(f);
                          }}
                        />
                      )}
                  </div>
                </Row>
              </div>
            </button>
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
                  <Text text03 mainBody>
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
  onFileClick?: (file: ProjectFile) => void;
  recentFiles: ProjectFile[];
  handleUploadChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  trigger?: React.ReactNode;
}

export default function FilePicker({
  className,
  onPickRecent,
  onFileClick,
  recentFiles,
  handleUploadChange,
  trigger,
}: FilePickerProps) {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [showRecentFiles, setShowRecentFiles] = useState(false);
  const [open, setOpen] = useState(false);

  const triggerUploadPicker = () => fileInputRef.current?.click();

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
            recentFiles={recentFiles}
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
          className="w-[32rem] rounded-16 border flex flex-col bg-background-tint-00"
          onClickOutside={() => setShowRecentFiles(false)}
        >
          <UserFilesModalContent
            title="Recent Files"
            description="Upload files or pick from your recent files."
            icon={SvgFiles}
            recentFiles={recentFiles}
            onPickRecent={(file) => {
              onPickRecent && onPickRecent(file);
              setShowRecentFiles(false);
            }}
            handleUploadChange={handleUploadChange}
            onFileClick={onFileClick}
            onClose={() => setShowRecentFiles(false)}
          />
        </CoreModal>
      )}
    </div>
  );
}
