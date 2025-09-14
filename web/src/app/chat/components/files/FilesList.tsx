"use client";

import React, { useMemo, useRef, useState } from "react";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import {
  FileIcon,
  Globe,
  Image as ImageIcon,
  FileText,
  Search,
  Loader2,
  Trash2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { ProjectFile } from "../../projects/ProjectsContext";
import { formatRelativeTime } from "../projects/project_utils";
import { FileUploadIcon } from "@/components/icons/icons";

interface FilesListProps {
  className?: string;
  recentFiles: ProjectFile[];
  onPickRecent?: (file: ProjectFile) => void;
  handleUploadChange?: (e: React.ChangeEvent<HTMLInputElement>) => void;
  showRemove?: boolean;
  onRemove?: (file: ProjectFile) => void;
}

const kindIcon = (kind: string, status?: string) => {
  if (String(status).toLowerCase() === "processing") {
    return <Loader2 className="h-4 w-4 animate-spin" />;
  }
  const normalized = kind.toLowerCase();
  if (normalized.includes("url") || normalized.includes("site"))
    return <Globe className="h-4 w-4" />;
  if (
    normalized.includes("image") ||
    normalized.includes("png") ||
    normalized.includes("jpg")
  )
    return <ImageIcon className="h-4 w-4" />;
  if (normalized.includes("txt") || normalized.includes("text"))
    return <FileText className="h-4 w-4" />;
  return <FileIcon className="h-4 w-4" />;
};

const getReadableFileType = (fileType: string | undefined | null): string => {
  if (!fileType) return "";
  const str = String(fileType);
  const idx = str.lastIndexOf("/");
  const val = idx >= 0 ? str.slice(idx + 1) : str;
  return val.toUpperCase();
};

export default function FilesList({
  className,
  recentFiles,
  onPickRecent,
  handleUploadChange,
  showRemove,
  onRemove,
}: FilesListProps) {
  const [search, setSearch] = useState("");
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const triggerUploadPicker = () => fileInputRef.current?.click();

  const filtered = useMemo(() => {
    const s = search.trim().toLowerCase();
    if (!s) return recentFiles;
    return recentFiles.filter((f) => f.name.toLowerCase().includes(s));
  }, [recentFiles, search]);

  return (
    <div className={cn("flex flex-col gap-3", className)}>
      <div className="flex items-center gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search files..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="h-9 pl-8"
            removeFocusRing
          />
        </div>
        {handleUploadChange && (
          <>
            <input
              ref={fileInputRef}
              type="file"
              className="hidden"
              multiple
              onChange={handleUploadChange}
              accept={"*/*"}
            />
            <button
              onClick={triggerUploadPicker}
              className="flex flex-row gap-2 items-center justify-center p-2 rounded-md bg-background-dark/75 hover:dark:bg-neutral-800/75 hover:bg-accent-background-hovered transition-all duration-150"
            >
              <FileUploadIcon className="text-text-darker dark:text-text-lighter" />
              <p className="text-sm text-text-darker dark:text-text-lighter whitespace-nowrap">
                Add Files
              </p>
            </button>
          </>
        )}
      </div>
      <Separator />
      <ScrollArea className="h-[320px] md:h-auto md:max-h-[70vh] pr-2">
        <div className="flex flex-col">
          {filtered.map((f) => (
            <button
              key={f.id}
              className={cn(
                "flex items-center justify-between gap-3 text-left rounded-md px-2 py-2 group",
                "hover:bg-background-chat-hover hover:text-neutral-900 dark:hover:text-neutral-50"
              )}
              onClick={() => onPickRecent && onPickRecent(f)}
            >
              <div className="flex items-center gap-3 min-w-0">
                {kindIcon(f.file_type, (f as any).status)}
                <div className="min-w-0">
                  <div className="truncate text-sm font-normal">{f.name}</div>
                  <div className="text-xs text-text-400 dark:text-neutral-400">
                    {(() => {
                      const s = String(f.status || "").toLowerCase();
                      const typeLabel = getReadableFileType(f.file_type);
                      if (s === "processing") return "Processing...";
                      if (s === "completed") return typeLabel;
                      return f.status ? f.status : typeLabel;
                    })()}
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-2 ml-3">
                {f.last_accessed_at && (
                  <div className="text-xs text-text-400 dark:text-neutral-400 whitespace-nowrap">
                    {formatRelativeTime(f.last_accessed_at)}
                  </div>
                )}
                {showRemove &&
                  String(f.status).toLowerCase() !== "processing" && (
                    <button
                      title="Remove from project"
                      aria-label="Remove file from project"
                      className="p-0 bg-transparent border-0 outline-none cursor-pointer opacity-0 group-hover:opacity-100 focus:opacity-100 transition-opacity duration-150"
                      onClick={(e) => {
                        e.stopPropagation();
                        onRemove && onRemove(f);
                      }}
                    >
                      <Trash2 className="h-4 w-4 text-neutral-600 hover:text-red-600 dark:text-neutral-400 dark:hover:text-red-400" />
                    </button>
                  )}
              </div>
            </button>
          ))}
          {filtered.length === 0 && (
            <div className="text-sm text-muted-foreground px-2 py-4">
              No files found.
            </div>
          )}
        </div>
      </ScrollArea>
    </div>
  );
}
