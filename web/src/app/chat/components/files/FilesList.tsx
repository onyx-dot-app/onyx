"use client";

import React, { useMemo, useRef, useState, useEffect } from "react";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Search, Loader2, Trash2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { ProjectFile } from "../../projects/ProjectsContext";
import { formatRelativeTime } from "../projects/project_utils";
import {
  FileUploadIcon,
  ImageIcon as ImageFileIcon,
} from "@/components/icons/icons";
import { DocumentIcon, OpenInNewIcon } from "@/components/icons/CustomIcons";

interface FilesListProps {
  className?: string;
  recentFiles: ProjectFile[];
  onPickRecent?: (file: ProjectFile) => void;
  handleUploadChange?: (e: React.ChangeEvent<HTMLInputElement>) => void;
  showRemove?: boolean;
  onRemove?: (file: ProjectFile) => void;
  onFileClick?: (file: ProjectFile) => void;
}

// Using the same visual pattern as FileCard: spinner when processing, otherwise a
// DocumentIcon wrapped in a small accent background.

const getFileExtension = (fileName: string): string => {
  const idx = fileName.lastIndexOf(".");
  if (idx === -1) return "";
  const ext = fileName.slice(idx + 1).toLowerCase();
  if (ext === "txt") return "PLAINTEXT";
  return ext.toUpperCase();
};

export default function FilesList({
  className,
  recentFiles,
  onPickRecent,
  handleUploadChange,
  showRemove,
  onRemove,
  onFileClick,
}: FilesListProps) {
  const [search, setSearch] = useState("");
  const [minHeight, setMinHeight] = useState<string>("320px");
  const [isScrollable, setIsScrollable] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const scrollContainerRef = useRef<HTMLDivElement | null>(null);
  const scrollAreaRef = useRef<HTMLDivElement | null>(null);
  const triggerUploadPicker = () => fileInputRef.current?.click();

  const filtered = useMemo(() => {
    const s = search.trim().toLowerCase();
    if (!s) return recentFiles;
    return recentFiles.filter((f) => f.name.toLowerCase().includes(s));
  }, [recentFiles, search]);

  // Track the container height before search starts
  useEffect(() => {
    if (!search && scrollContainerRef.current) {
      // Use requestAnimationFrame to ensure DOM has updated
      requestAnimationFrame(() => {
        if (scrollContainerRef.current) {
          const containerHeight = scrollContainerRef.current.offsetHeight;

          // Only update if the new height is larger than current minHeight
          const currentMin = parseInt(minHeight);
          if (containerHeight > currentMin) {
            setMinHeight(`${containerHeight}px`);
          }
        }
      });
    }
  }, [recentFiles.length]); // Only track when file count changes, not search

  // Check if content is scrollable
  useEffect(() => {
    const checkScrollable = () => {
      if (scrollAreaRef.current) {
        const viewport = scrollAreaRef.current.querySelector(
          "[data-radix-scroll-area-viewport]"
        );
        if (viewport) {
          const isContentScrollable =
            viewport.scrollHeight > viewport.clientHeight;
          setIsScrollable(isContentScrollable);
        }
      }
    };

    // Check initially and after content changes
    requestAnimationFrame(checkScrollable);

    // Also check on resize
    window.addEventListener("resize", checkScrollable);
    return () => window.removeEventListener("resize", checkScrollable);
  }, [filtered.length, minHeight]);

  return (
    <div
      className={cn("flex flex-col gap-2 focus:outline-none w-full", className)}
      tabIndex={-1}
      onMouseDown={(e) => {
        // Prevent parent dialog from intercepting mouse events
        e.stopPropagation();
      }}
    >
      <div className="flex items-center gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
          <Input
            placeholder="Search files..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="h-9 pl-8 bg-transparent border-0 shadow-none focus:bg-transparent focus:ring-0 focus-visible:ring-0 focus:border focus:border-border-dark"
            removeFocusRing
            autoComplete="off"
            tabIndex={0}
            onFocus={(e) => {
              // Select all text when focused
              e.target.select();
            }}
            onClick={(e) => {
              // Force focus on click
              e.stopPropagation();
              e.currentTarget.focus();
            }}
            onMouseDown={(e) => {
              // Prevent dialog from interfering with input clicks
              e.stopPropagation();
            }}
            onPointerDown={(e) => {
              // Handle touch/pointer events
              e.stopPropagation();
            }}
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
      <div
        ref={scrollContainerRef}
        className="transition-all duration-200 relative"
        style={{
          minHeight: minHeight,
          height: search ? minHeight : "auto",
          maxHeight: "588px", // ~10.5 items * 56px per item
        }}
      >
        <ScrollArea ref={scrollAreaRef} className="h-full pr-1">
          <div className="flex flex-col">
            {filtered.map((f) => (
              <button
                key={f.id}
                className={cn(
                  "flex items-center justify-between gap-3 text-left rounded-md px-2 py-2 group border border-transparent",
                  "hover:bg-background-chat-hover hover:text-neutral-900 dark:hover:text-neutral-50 hover:border-border-dark dark:hover:border-border-light"
                )}
                onClick={() => {
                  if (onPickRecent) {
                    onPickRecent(f);
                  }
                }}
              >
                <div className="flex items-center gap-3 min-w-0">
                  <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-transparent">
                    {String((f as any).status).toLowerCase() ===
                    "processing" ? (
                      <Loader2 className="h-5 w-5 text-onyx-medium animate-spin" />
                    ) : (
                      <div className="bg-accent-background p-2 rounded-lg shadow-sm">
                        {(() => {
                          const ext = getFileExtension(f.name).toLowerCase();
                          const isImage = [
                            "png",
                            "jpg",
                            "jpeg",
                            "gif",
                            "webp",
                            "svg",
                            "bmp",
                          ].includes(ext);
                          return isImage ? (
                            <ImageFileIcon
                              size={20}
                              className="text-onyx-muted"
                            />
                          ) : (
                            <DocumentIcon className="h-5 w-5 text-onyx-muted" />
                          );
                        })()}
                      </div>
                    )}
                  </div>
                  <div className="min-w-0">
                    <div className="truncate text-sm font-normal">{f.name}</div>
                    <div className="text-xs text-text-400 dark:text-neutral-400">
                      {(() => {
                        const s = String(f.status || "").toLowerCase();
                        const typeLabel = getFileExtension(f.name);
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
                  {onFileClick &&
                    String(f.status).toLowerCase() !== "processing" && (
                      <button
                        title="View file"
                        aria-label="View file"
                        className="p-0 bg-transparent border-0 outline-none cursor-pointer opacity-0 group-hover:opacity-100 focus:opacity-100 transition-opacity duration-150"
                        onClick={(e) => {
                          e.stopPropagation();
                          e.preventDefault();
                          onFileClick && onFileClick(f);
                        }}
                      >
                        <OpenInNewIcon
                          size={16}
                          className="text-neutral-600 hover:text-neutral-900 dark:text-neutral-400 dark:hover:text-neutral-200"
                        />
                      </button>
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
        {/* Fade effect at bottom when scrollable */}
        {isScrollable && (
          <div className="absolute bottom-0 left-0 right-0 h-16 bg-gradient-to-t from-background via-background/90 to-transparent pointer-events-none z-10" />
        )}
      </div>
    </div>
  );
}
