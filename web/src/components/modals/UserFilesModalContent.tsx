"use client";

import React, { useMemo, useRef, useState, useEffect } from "react";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import IconButton from "@/refresh-components/buttons/IconButton";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { ProjectFile } from "@/app/chat/projects/ProjectsContext";
import { formatRelativeTime } from "@/app/chat/components/projects/project_utils";
import LineItem from "@/refresh-components/buttons/LineItem";
import SvgPlusCircle from "@/icons/plus-circle";
import Text from "@/refresh-components/Text";
import SvgX from "@/icons/x";
import { SvgProps } from "@/icons";
import SvgSearch from "@/icons/search";
import SvgExternalLink from "@/icons/external-link";
import SvgFileText from "@/icons/file-text";
import SvgImage from "@/icons/image";
import SvgTrash from "@/icons/trash";
import SvgCheck from "@/icons/check";
import Truncated from "@/refresh-components/Truncated";
import { isImageExtension } from "@/app/chat/components/files/files_utils";

interface UserFilesModalProps {
  title: string;
  description: string;
  icon: React.FunctionComponent<SvgProps>;
  recentFiles: ProjectFile[];
  onPickRecent?: (file: ProjectFile) => void;
  onUnpickRecent?: (file: ProjectFile) => void;
  handleUploadChange?: (e: React.ChangeEvent<HTMLInputElement>) => void;
  showRemove?: boolean;
  onRemove?: (file: ProjectFile) => void;
  onFileClick?: (file: ProjectFile) => void;
  onClose?: () => void;
  selectedFileIds?: string[];
  /**
   * If provided, forces the scrollable content area of the modal
   * to a fixed height (in pixels). This ensures consistent modal
   * heights across different usages regardless of content size.
   */
  fixedHeight?: number;
}

const getFileExtension = (fileName: string): string => {
  const idx = fileName.lastIndexOf(".");
  if (idx === -1) return "";
  const ext = fileName.slice(idx + 1).toLowerCase();
  if (ext === "txt") return "PLAINTEXT";
  return ext.toUpperCase();
};

export default function UserFilesModalContent({
  title,
  description,
  icon: Icon,
  recentFiles,
  onPickRecent,
  onUnpickRecent,
  handleUploadChange,
  showRemove,
  onRemove,
  onFileClick,
  onClose,
  selectedFileIds,
  fixedHeight,
}: UserFilesModalProps) {
  const [search, setSearch] = useState("");
  const [containerHeight, setContainerHeight] = useState<number>(
    typeof fixedHeight === "number" ? fixedHeight : 320
  );
  const [isScrollable, setIsScrollable] = useState(false);
  const [scrollFadeOpacity, setScrollFadeOpacity] = useState(0);
  const [bottomFadeOpacity, setBottomFadeOpacity] = useState(0);
  const [isInitialMount, setIsInitialMount] = useState(true);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(
    () => new Set(selectedFileIds || [])
  );
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const scrollContainerRef = useRef<HTMLDivElement | null>(null);
  const scrollAreaRef = useRef<HTMLDivElement | null>(null);
  const maxHeight = typeof fixedHeight === "number" ? fixedHeight : 588;
  const minHeight = typeof fixedHeight === "number" ? fixedHeight : 320;
  const triggerUploadPicker = () => fileInputRef.current?.click();

  useEffect(() => {
    if (selectedFileIds) {
      setSelectedIds(new Set(selectedFileIds));
    } else {
      setSelectedIds(new Set());
    }
  }, [selectedFileIds]);

  const filtered = useMemo(() => {
    const s = search.trim().toLowerCase();
    if (!s) return recentFiles;
    return recentFiles.filter((f) => f.name.toLowerCase().includes(s));
  }, [recentFiles, search]);

  // Track container height - only grow, never shrink (disabled when fixedHeight is set)
  useEffect(() => {
    if (typeof fixedHeight === "number") return; // fixed height => skip dynamic sizing
    if (scrollAreaRef.current) {
      requestAnimationFrame(() => {
        if (scrollAreaRef.current) {
          const viewport = scrollAreaRef.current.querySelector(
            "[data-radix-scroll-area-viewport]"
          );
          if (viewport) {
            const contentHeight = viewport.scrollHeight;
            // Only update if content needs more space and we haven't hit max
            const newHeight = Math.min(
              Math.max(contentHeight, minHeight, containerHeight),
              maxHeight
            );
            if (newHeight > containerHeight) {
              setContainerHeight(newHeight);
            }
            // After initial mount, enable transitions
            if (isInitialMount) {
              setTimeout(() => setIsInitialMount(false), 50);
            }
          }
        }
      });
    }
  }, [
    recentFiles.length,
    containerHeight,
    isInitialMount,
    fixedHeight,
    minHeight,
    maxHeight,
  ]);

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
  }, [filtered.length, containerHeight]);

  // Track scroll position for smooth fade opacity
  useEffect(() => {
    const handleScroll = () => {
      if (scrollAreaRef.current) {
        const viewport = scrollAreaRef.current.querySelector(
          "[data-radix-scroll-area-viewport]"
        );
        if (viewport) {
          const scrollTop = viewport.scrollTop;
          const scrollHeight = viewport.scrollHeight;
          const clientHeight = viewport.clientHeight;

          // Top fade: Fade in over 40px of scroll (0-40px = 0-1 opacity)
          const fadeDistance = 40;
          const topOpacity = Math.min(scrollTop / fadeDistance, 1);
          setScrollFadeOpacity(topOpacity);

          // Bottom fade: Calculate distance from bottom
          const scrollBottom = scrollHeight - scrollTop - clientHeight;
          const bottomOpacity = Math.min(scrollBottom / fadeDistance, 1);
          setBottomFadeOpacity(bottomOpacity);
        }
      }
    };

    if (scrollAreaRef.current) {
      const viewport = scrollAreaRef.current.querySelector(
        "[data-radix-scroll-area-viewport]"
      );
      if (viewport) {
        viewport.addEventListener("scroll", handleScroll);
        // Initial calculation
        handleScroll();
        return () => viewport.removeEventListener("scroll", handleScroll);
      }
    }
  }, [scrollAreaRef.current]);

  return (
    <>
      <div className="shadow-01 relative z-20 w-full">
        <div className="flex flex-col gap-spacing-paragraph p-spacing-paragraph">
          <div className="flex flex-row justify-between items-center w-full">
            <div className="flex items-center gap-2">
              <Icon className="w-[1.5rem] h-[1.5rem] stroke-text-04" />
              <Text headingH3 text04>
                {title}
              </Text>
            </div>
            {onClose && <IconButton icon={SvgX} internal onClick={onClose} />}
          </div>
          <Text text03>{description}</Text>
        </div>
        <div
          tabIndex={-1}
          onMouseDown={(e) => {
            e.stopPropagation();
          }}
        >
          <div className="flex items-center gap-spacing-paragraph p-spacing-paragraph">
            <div className="relative flex-1">
              <SvgSearch className="absolute left-2 top-1/2 -translate-y-1/2 h-4 w-4 stroke-text-02 pointer-events-none" />
              <Input
                placeholder="Search files..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="h-10 pl-8 bg-transparent border border-border-dark shadow-none focus:bg-transparent focus:ring-0 focus-visible:ring-0"
                removeFocusRing
                autoComplete="off"
                tabIndex={0}
                onFocus={(e) => {
                  e.target.select();
                }}
                onClick={(e) => {
                  e.stopPropagation();
                  e.currentTarget.focus();
                }}
                onMouseDown={(e) => {
                  e.stopPropagation();
                }}
                onPointerDown={(e) => {
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

                <div className="ml-spacing-interline">
                  <LineItem icon={SvgPlusCircle} onClick={triggerUploadPicker}>
                    <Text text03 mainUiAction>
                      Add Files
                    </Text>
                  </LineItem>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
      <div
        ref={scrollContainerRef}
        className={cn(
          "relative w-full",
          !isInitialMount && "transition-all duration-200"
        )}
        style={{
          height: `${containerHeight}px`,
          maxHeight: `${maxHeight}px`,
        }}
      >
        <div
          className="absolute top-0 left-0 right-0 h-8 pointer-events-none z-10 transition-opacity duration-200"
          style={{
            opacity: scrollFadeOpacity,
            background:
              "linear-gradient(to bottom, var(--background-tint-01) 0%, transparent 100%)",
          }}
        />
        <div
          className="absolute bottom-0 left-0 right-0 h-8 pointer-events-none z-10 transition-opacity duration-200"
          style={{
            opacity: bottomFadeOpacity,
            background:
              "linear-gradient(to top, var(--background-tint-01) 0%, transparent 100%)",
          }}
        />
        <ScrollArea
          ref={scrollAreaRef}
          className="h-full bg-background-tint-01"
        >
          <div className="grid grid-cols-3 gap-spacing-interline p-spacing-paragraph">
            {filtered.map((f) => {
              const s = String((f as ProjectFile).status || "").toLowerCase();
              const isProcessing = s === "processing" || s === "uploading";
              const isSelected = onPickRecent ? selectedIds.has(f.id) : false;
              const typeLabel = getFileExtension(f.name);

              return (
                <div
                  role="button"
                  tabIndex={0}
                  key={f.id}
                  className={cn(
                    "relative group select-none rounded-12 bg-background-tint-00 p-spacing-paragraph flex flex-col gap-2 border border-transparent shadow-sm",
                    onPickRecent && "hover:bg-background-tint-02",
                    isSelected && "border-action-link-05"
                  )}
                  onClick={() => {
                    if (!onPickRecent) return;
                    if (isSelected) {
                      onUnpickRecent?.(f);
                      setSelectedIds((prev) => {
                        const next = new Set(prev);
                        next.delete(f.id);
                        return next;
                      });
                    } else {
                      onPickRecent(f);
                      setSelectedIds((prev) => {
                        const next = new Set(prev);
                        next.add(f.id);
                        return next;
                      });
                    }
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      e.currentTarget.click();
                    }
                  }}
                >
                  {/* Name row with type icon and inline actions */}
                  <div className="flex items-center gap-2 min-w-0">
                    {isProcessing ? (
                      <div className="flex h-6 w-6 items-center justify-center bg-background-neutral-00 group-hover:!bg-background-tint-02 rounded-04 transition-colors duration-150">
                        <Loader2 className="h-4 w-4 text-text-02 animate-spin" />
                      </div>
                    ) : onPickRecent && isSelected ? (
                      <div className="flex h-6 w-6 items-center justify-center rounded-04 border border-border-01 bg-background-neutral-00 group-hover:!bg-background-tint-02 transition-colors duration-150">
                        <SvgCheck className="h-3 w-3 stroke-text-02" />
                      </div>
                    ) : (
                      <div className="flex h-6 w-6 items-center justify-center bg-background-neutral-00 group-hover:!bg-background-tint-02 rounded-04 transition-colors duration-150">
                        {(() => {
                          const ext = typeLabel.toLowerCase();
                          const isImage = isImageExtension(ext);
                          return isImage ? (
                            <SvgImage className="h-4 w-4 stroke-text-02" />
                          ) : (
                            <SvgFileText className="h-4 w-4 stroke-text-02" />
                          );
                        })()}
                      </div>
                    )}
                    <div className="relative flex-1 min-w-0">
                      <div
                        className="w-full text-left"
                        style={{
                          maskImage:
                            "linear-gradient(to right, black calc(100% - 3rem), transparent 100%)",
                          WebkitMaskImage:
                            "linear-gradient(to right, black calc(100% - 3rem), transparent 100%)",
                        }}
                      >
                        <Truncated text04 mainUiBody nowrap>
                          {f.name}
                        </Truncated>
                      </div>
                    </div>
                    {(onFileClick || showRemove) && (
                      <div className="ml-2 flex items-center gap-1 opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity duration-150 shrink-0">
                        {onFileClick && !isProcessing && (
                          <IconButton
                            internal
                            icon={SvgExternalLink}
                            tooltip="View file"
                            className="p-0 bg-transparent hover:bg-transparent"
                            onClick={(e) => {
                              e.stopPropagation();
                              e.preventDefault();
                              onFileClick(f);
                            }}
                          />
                        )}
                        {showRemove && !isProcessing && (
                          <IconButton
                            internal
                            icon={SvgTrash}
                            tooltip="Remove from project"
                            className="p-0 bg-transparent hover:bg-transparent"
                            onClick={(e) => {
                              e.stopPropagation();
                              onRemove && onRemove(f);
                            }}
                          />
                        )}
                      </div>
                    )}
                  </div>

                  <div className="flex items-center justify-between">
                    <Text text03 secondaryBody>
                      {(() => {
                        // In selection mode (Recent Files modal), show only the file type label
                        if (onPickRecent && !showRemove) {
                          return typeLabel;
                        }
                        // In management contexts, preserve status semantics
                        if (s === "processing") return "Processing...";
                        if (s === "uploading") return "Uploading...";
                        if (s === "completed") return typeLabel;
                        return f.status ? f.status : typeLabel;
                      })()}
                    </Text>
                    {f.last_accessed_at && (
                      <Text text03 secondaryBody nowrap>
                        {formatRelativeTime(f.last_accessed_at)}
                      </Text>
                    )}
                  </div>
                </div>
              );
            })}
          </div>

          {filtered.length === 0 && (
            <Text text03 secondaryBody className="px-2 py-4">
              No files found.
            </Text>
          )}
        </ScrollArea>
      </div>
    </>
  );
}
