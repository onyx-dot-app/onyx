"use client";
import React, { useMemo, useRef, useState } from "react";
import {
  Menubar,
  MenubarContent,
  MenubarItem,
  MenubarMenu,
  MenubarSeparator,
  MenubarTrigger,
} from "@/components/ui/menubar";
import { FileUploadIcon } from "@/components/icons/icons";
import { Files } from "@phosphor-icons/react";
import { FileIcon, Paperclip, Loader2, Eye } from "lucide-react";
import { cn } from "@/lib/utils";
import { ChatInputOption } from "../input/ChatInputOption";
import FilesList from "./FilesList";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ProjectFile } from "../../projects/projectsService";

type FilePickerProps = {
  className?: string;
  onPickRecent?: (file: ProjectFile) => void;
  onFileClick?: (file: ProjectFile) => void;
  recentFiles: ProjectFile[];
  handleUploadChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  showTriggerLabel?: boolean;
  triggerLabel?: string;
  triggerLabelClassName?: string;
  triggerClassName?: string;
};

// Small helper to render an icon + label row
const Row = ({ children }: { children: React.ReactNode }) => (
  <div className="flex items-center gap-2">{children}</div>
);

export default function FilePicker({
  className,
  onPickRecent,
  onFileClick,
  recentFiles,
  handleUploadChange,
  showTriggerLabel = false,
  triggerLabel = "Add Files",
  triggerLabelClassName = "",
  triggerClassName = "",
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
      <Menubar className="bg-transparent dark:bg-transparent p-0 border-0">
        <MenubarMenu>
          <MenubarTrigger className="relative cursor-pointer flex items-center group rounded-lg text-input-text py-1.5 px-0 h-8">
            {showTriggerLabel ? (
              <div
                className={cn(
                  "flex flex-row gap-2 items-center justify-center p-2 rounded-md bg-background-dark/75 hover:dark:bg-neutral-800/75 hover:bg-accent-background-hovered transition-all duration-150",
                  triggerClassName
                )}
              >
                <FileUploadIcon className="text-text-darker dark:text-text-lighter" />
                <p
                  className={cn(
                    "text-text-darker dark:text-text-lighter",
                    triggerLabelClassName
                  )}
                >
                  {triggerLabel}
                </p>
              </div>
            ) : (
              <Row>
                <ChatInputOption
                  flexPriority="stiff"
                  Icon={FileUploadIcon}
                  tooltipContent={"Upload files and attach user files"}
                />
              </Row>
            )}
          </MenubarTrigger>
          <MenubarContent
            align="start"
            sideOffset={6}
            className="min-w-[220px] text-input-text"
          >
            {recentFiles.length > 0 && (
              <>
                <label className="text-sm font-light text-input-text p-2.5">
                  Recent Files
                </label>
                {recentFiles.slice(0, 3).map((f) => (
                  <MenubarItem
                    key={f.id}
                    onClick={() =>
                      onPickRecent
                        ? onPickRecent(f)
                        : console.log("Picked recent", f)
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
                  <MenubarItem
                    onClick={() => setShowRecentFiles(true)}
                    className="m-1 rounded-lg hover:bg-background-chat-hover hover:text-neutral-900 dark:hover:text-neutral-50 text-input-text p-2 font-normal"
                  >
                    <Row>
                      <span className="truncate font-light">
                        ... All Recent Files
                      </span>
                    </Row>
                  </MenubarItem>
                )}
                <MenubarSeparator />
              </>
            )}

            <MenubarItem
              onClick={triggerUploadPicker}
              className="m-1 rounded-lg hover:bg-background-chat-hover hover:text-neutral-900 dark:hover:text-neutral-50 text-input-text p-2"
            >
              <Row>
                <Paperclip size={16} />
                <div className="flex flex-col">
                  <span className="font-semibold">Upload Files</span>
                  <span className="text-xs font-description text-text-400 dark:text-neutral-400">
                    Upload a file from your device
                  </span>
                </div>
              </Row>
            </MenubarItem>
          </MenubarContent>
        </MenubarMenu>
      </Menubar>

      <Dialog open={showRecentFiles} onOpenChange={setShowRecentFiles}>
        <DialogContent
          className="w-full max-w-lg focus:outline-none focus-visible:outline-none"
          tabIndex={-1}
          onOpenAutoFocus={(e) => {
            // Prevent auto-focus which can interfere with input
            e.preventDefault();
          }}
        >
          <DialogHeader>
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
