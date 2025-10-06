"use client";

import React, { useRef, useState } from "react";
import {
  Menubar,
  MenubarContent,
  MenubarItem,
  MenubarMenu,
  MenubarSeparator,
  MenubarTrigger,
} from "@/components/ui/menubar";
import { Files } from "@phosphor-icons/react";
import { FileIcon, Loader2, Eye } from "lucide-react";
import { cn } from "@/lib/utils";
import FilesList from "./FilesList";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ProjectFile } from "../../projects/projectsService";
import LineItem from "@/refresh-components/buttons/LineItem";
import SvgPaperclip from "@/icons/paperclip";
import IconButton from "@/refresh-components/buttons/IconButton";
import SvgPlusCircle from "@/icons/plus-circle";

// Small helper to render an icon + label row
const Row = ({ children }: { children: React.ReactNode }) => (
  <div className="flex items-center gap-2">{children}</div>
);

interface FilePickerContentsProps {
  recentFiles: ProjectFile[];
  onPickRecent?: (file: ProjectFile) => void;
  onFileClick?: (file: ProjectFile) => void;
  triggerUploadPicker: () => void;
  setShowRecentFiles: (show: boolean) => void;
}

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
          <label className="text-sm font-light text-input-text p-2.5">
            Recent Files
          </label>

          {recentFiles.slice(0, 3).map((f) => (
            <MenubarItem
              key={f.id}
              onClick={() =>
                onPickRecent ? onPickRecent(f) : console.log("Picked recent", f)
              }
              className="m-1 rounded-lg hover:bg-background-chat-hover hover:text-neutral-900 dark:hover:text-neutral-50 text-input-text p-2 group"
            >
              <div className="flex items-center justify-between w-full">
                <Row>
                  {String(f.status).toLowerCase() === "processing" ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <FileIcon className="h-4 w-4" />
                  )}
                  <span className="truncate max-w-[160px]" title={f.name}>
                    {f.name}
                  </span>
                </Row>
                {onFileClick &&
                  String(f.status).toLowerCase() !== "processing" && (
                    <button
                      title="View file"
                      aria-label="View file"
                      className="p-0 bg-transparent border-0 outline-none cursor-pointer opacity-0 group-hover:opacity-100 focus:opacity-100 transition-opacity duration-150 ml-2"
                      onClick={(e) => {
                        e.stopPropagation();
                        e.preventDefault();
                        onFileClick && onFileClick(f);
                      }}
                    >
                      <Eye className="h-4 w-4 text-neutral-600 hover:text-neutral-900 dark:text-neutral-400 dark:hover:text-neutral-200" />
                    </button>
                  )}
              </div>
            </MenubarItem>
          ))}

          {recentFiles.length > 3 && (
            <LineItem onClick={() => setShowRecentFiles(true)}>
              ... All Recent Files
            </LineItem>
          )}

          <MenubarSeparator />
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
  showTriggerLabel?: boolean;
  triggerLabel?: string;
  triggerLabelClassName?: string;
  triggerClassName?: string;
}

export default function FilePicker({
  className,
  onPickRecent,
  onFileClick,
  recentFiles,
  handleUploadChange,
  showTriggerLabel = false,
  triggerLabel = "Add Files",
}: FilePickerProps) {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [showRecentFiles, setShowRecentFiles] = useState(false);

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
      <Menubar className="bg-transparent dark:bg-transparent p-0 border-0 h-8">
        <MenubarMenu>
          <MenubarTrigger className="relative cursor-pointer flex items-center group rounded-lg text-input-text px-0 h-8">
            {showTriggerLabel ? (
              <LineItem icon={SvgPlusCircle}>{triggerLabel}</LineItem>
            ) : (
              <IconButton
                icon={SvgPlusCircle}
                tooltip="Attach Files"
                tertiary
              />
            )}
          </MenubarTrigger>
          <MenubarContent
            align="start"
            sideOffset={6}
            className="min-w-[220px] text-input-text"
          >
            <FilePickerContents
              recentFiles={recentFiles}
              onPickRecent={onPickRecent}
              onFileClick={onFileClick}
              triggerUploadPicker={triggerUploadPicker}
              setShowRecentFiles={setShowRecentFiles}
            />
          </MenubarContent>
        </MenubarMenu>
      </Menubar>

      <Dialog open={showRecentFiles} onOpenChange={setShowRecentFiles}>
        <DialogContent
          className="w-full max-w-lg px-6 py-3 sm:px-6 sm:py-4 focus:outline-none focus-visible:outline-none"
          tabIndex={-1}
          onOpenAutoFocus={(e) => {
            // Prevent auto-focus which can interfere with input
            e.preventDefault();
          }}
        >
          <DialogHeader className="px-0 pt-0 pb-2">
            <Files size={32} />
            <DialogTitle>Recent Files</DialogTitle>
          </DialogHeader>
          <FilesList
            recentFiles={recentFiles}
            onPickRecent={onPickRecent}
            onFileClick={onFileClick}
            handleUploadChange={handleUploadChange}
          />
        </DialogContent>
      </Dialog>
    </div>
  );
}
