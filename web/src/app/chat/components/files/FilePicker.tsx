"use client";
import React, { useMemo, useRef, useState } from "react";
import {
  Menubar,
  MenubarContent,
  MenubarItem,
  MenubarMenu,
  MenubarSeparator,
  MenubarShortcut,
  MenubarTrigger,
} from "@/components/ui/menubar";
import { FileUploadIcon } from "@/components/icons/icons";
import { Files } from "@phosphor-icons/react";
import { FileIcon, Paperclip } from "lucide-react";
import { cn } from "@/lib/utils";
import { ChatInputOption } from "../input/ChatInputOption";
import FilesList from "./FilesList";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ProjectFile } from "../../projects/ProjectsContext";

type FilePickerProps = {
  className?: string;
  onPickRecent?: (fileId: string) => void;
  recentFiles: ProjectFile[];
};

// Small helper to render an icon + label row
const Row = ({ children }: { children: React.ReactNode }) => (
  <div className="flex items-center gap-2">{children}</div>
);

export default function FilePicker({
  className,
  onPickRecent,
  recentFiles,
}: FilePickerProps) {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [showRecentFiles, setShowRecentFiles] = useState(false);

  const triggerUploadPicker = () => fileInputRef.current?.click();

  const handleUploadChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;
    setIsUploading(true);
    try {
      // Dummy handler: just log selected file names
      const names = Array.from(files).map((f) => f.name);
      console.log("Selected files:", names);
    } finally {
      setIsUploading(false);
      e.target.value = ""; // reset input
    }
  };

  const handleUrlAdd = async () => {
    const url = window.prompt("Paste a URL to add as a file");
    if (!url) return;
    try {
      // Dummy handler: log URL
      console.log("URL added:", url);
    } catch (e) {
      // swallow; upstream surfaces errors
    }
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
      <Menubar className="bg-transparent dark:bg-transparent p-0 border-0">
        <MenubarMenu>
          <MenubarTrigger className="relative cursor-pointer flex items-center group rounded-lg text-input-text hover:bg-background-chat-hover hover:text-neutral-900 dark:hover:text-neutral-50 py-1.5 px-0">
            <Row>
              {/* <FileUploadIcon size={16} />
              <span className="sr-only">Add files</span> */}
              <ChatInputOption
                flexPriority="stiff"
                Icon={FileUploadIcon}
                tooltipContent={"Upload files and attach user files"}
              />
            </Row>
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
                        ? onPickRecent(f.id)
                        : console.log("Picked recent", f)
                    }
                    className="hover:bg-background-chat-hover hover:text-neutral-900 dark:hover:text-neutral-50 text-input-text p-2"
                  >
                    <Row>
                      <FileIcon className="h-4 w-4" />
                      <span className="truncate max-w-[160px]" title={f.name}>
                        {f.name}
                      </span>
                    </Row>
                  </MenubarItem>
                ))}
                {recentFiles.length > 3 && (
                  <MenubarItem
                    onClick={() => setShowRecentFiles(true)}
                    className="hover:bg-background-chat-hover hover:text-neutral-900 dark:hover:text-neutral-50 text-input-text p-2 font-normal"
                  >
                    <Row>
                      <span className="truncate font-light">
                        ... All Recent Files
                      </span>
                    </Row>
                  </MenubarItem>
                )}
              </>
            )}
            <MenubarSeparator />
            <MenubarItem
              onClick={triggerUploadPicker}
              disabled={isUploading}
              className="hover:bg-background-chat-hover hover:text-neutral-900 dark:hover:text-neutral-50 text-input-text p-2"
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
        <DialogContent className="w-full max-w-lg">
          <DialogHeader>
            <Files size={32} />
            <DialogTitle>Recent Files</DialogTitle>
          </DialogHeader>
          <FilesList recentFiles={recentFiles} onPickRecent={onPickRecent} />
        </DialogContent>
      </Dialog>
    </div>
  );
}
