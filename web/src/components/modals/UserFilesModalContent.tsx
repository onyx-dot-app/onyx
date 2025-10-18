"use client";

import React, { useMemo, useRef, useState, useEffect } from "react";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import { ScrollArea } from "@/components/ui/scroll-area";
import IconButton from "@/refresh-components/buttons/IconButton";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { ProjectFile } from "@/app/chat/projects/ProjectsContext";
import { formatRelativeTime } from "@/app/chat/components/projects/project_utils";
import Button from "@/refresh-components/buttons/Button";
import SvgPlusCircle from "@/icons/plus-circle";
import Text from "@/refresh-components/texts/Text";
import SvgX from "@/icons/x";
import { SvgProps } from "@/icons";
import SvgExternalLink from "@/icons/external-link";
import SvgFileText from "@/icons/file-text";
import SvgImage from "@/icons/image";
import SvgTrash from "@/icons/trash";
import SvgCheck from "@/icons/check";
import Truncated from "@/refresh-components/texts/Truncated";
import { isImageExtension } from "@/app/chat/components/files/files_utils";
import { UserFileStatus } from "@/app/chat/projects/projectsService";
import LineItem from "@/refresh-components/buttons/LineItem";

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
}: UserFilesModalProps) {
  const [search, setSearch] = useState("");
  const [containerHeight, setContainerHeight] = useState<number>(320);
  const [isScrollable, setIsScrollable] = useState(false);
  const [isInitialMount, setIsInitialMount] = useState(true);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(
    () => new Set(selectedFileIds || [])
  );
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const scrollContainerRef = useRef<HTMLDivElement | null>(null);
  const scrollAreaRef = useRef<HTMLDivElement | null>(null);
  const maxHeight = 588;
  const minHeight = 320;
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

  // Track container height - only grow, never shrink
  useEffect(() => {
    let timeoutId: number | undefined;
    let rafId: number | undefined;

    if (scrollAreaRef.current) {
      rafId = requestAnimationFrame(() => {
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
              timeoutId = window.setTimeout(() => setIsInitialMount(false), 50);
            }
          }
        }
      });
    }

    return () => {
      if (timeoutId !== undefined) {
        window.clearTimeout(timeoutId);
      }
      if (rafId !== undefined) {
        cancelAnimationFrame(rafId);
      }
    };
  }, [recentFiles.length, containerHeight, isInitialMount]);

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

  return (
    <>
      <div className="shadow-01 rounded-t-12 relative z-20">
        <div className="flex flex-col gap-spacing-inline px-spacing-paragraph pt-spacing-paragraph">
          <div className="h-[1.5rem] flex flex-row justify-between items-center w-full">
            <Icon className="w-[1.5rem] h-[1.5rem] stroke-text-04" />
            {onClose && <IconButton icon={SvgX} internal onClick={onClose} />}
          </div>
          <Text headingH3 text04 className="w-full text-left">
            {title}
          </Text>
          <Text text03>{description}</Text>
        </div>
        <div
          tabIndex={-1}
          onMouseDown={(e) => {
            e.stopPropagation();
          }}
        >
          <div className="flex items-center gap-2 p-spacing-interline">
            <div className="relative flex-1">
              <InputTypeIn
                placeholder="Search files..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                leftSearchIcon
                autoComplete="off"
                tabIndex={0}
                onFocus={(e) => {
                  e.target.select();
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

                <div>
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
          "relative rounded-b-12",
          !isInitialMount && "transition-all duration-200"
        )}
        style={{
          height: `${containerHeight}px`,
          maxHeight: `${maxHeight}px`,
        }}
      >
        <ScrollArea
          ref={scrollAreaRef}
          className="flex flex-col h-full bg-background-tint-01 px-spacing-paragraph rounded-b-12"
        >
          {filtered.map((f) => (
            <div
              role="button"
              tabIndex={0}
              key={f.id}
              className={cn(
                "flex items-center justify-between gap-3 text-left p-spacing-inline rounded-12 bg-background-tint-00 w-full my-spacing-inline group",
                onPickRecent && "hover:bg-background-tint-02"
              )}
              onClick={() => {
                if (!onPickRecent) return;
                const isSelected = selectedIds.has(f.id);
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
              <div className="flex items-center p-spacing-inline flex-1 min-w-0">
                <div className="flex h-9 w-9 items-center justify-center p-spacing-interline bg-background-tint-01 rounded-08">
                  {String((f as ProjectFile).status) ===
                    UserFileStatus.PROCESSING ||
                  String((f as ProjectFile).status) ===
                    UserFileStatus.UPLOADING ||
                  String((f as ProjectFile).status) ===
                    UserFileStatus.DELETING ? (
                    <Loader2 className="h-5 w-5 text-text-02 animate-spin" />
                  ) : (
                    <>
                      {onPickRecent && selectedIds.has(f.id) ? (
                        <div className="w-4 h-4 flex items-center justify-center rounded-04 border border-border-01 bg-background-neutral-00 p-spacing-inline-mini">
                          <SvgCheck className="stroke-text-02" />
                        </div>
                      ) : (
                        (() => {
                          const ext = getFileExtension(f.name).toLowerCase();
                          const isImage = isImageExtension(ext);
                          return isImage ? (
                            <SvgImage className="h-5 w-5 stroke-text-02" />
                          ) : (
                            <SvgFileText className="h-5 w-5 stroke-text-02" />
                          );
                        })()
                      )}
                    </>
                  )}
                </div>
                <div className="p-spacing-inline-mini flex-1 min-w-0">
                  <div className="flex items-center gap-2 min-w-0">
                    <div className="max-w-[250px] min-w-0 flex-none">
                      <Truncated text04 secondaryAction nowrap>
                        {f.name}
                      </Truncated>
                    </div>
                    {onFileClick &&
                      String(f.status) !== UserFileStatus.PROCESSING &&
                      String(f.status) !== UserFileStatus.UPLOADING &&
                      String(f.status) !== UserFileStatus.DELETING && (
                        <IconButton
                          internal
                          icon={SvgExternalLink}
                          tooltip="View file"
                          className="opacity-0 group-hover:opacity-100 focus:opacity-100 transition-opacity duration-150 p-0  shrink-0"
                          onClick={(e) => {
                            e.stopPropagation();
                            e.preventDefault();
                            onFileClick(f);
                          }}
                        />
                      )}
                  </div>

                  <Text text03 secondaryBody>
                    {(() => {
                      const s = String(f.status || "");
                      const typeLabel = getFileExtension(f.name);
                      if (s === UserFileStatus.PROCESSING)
                        return "Processing...";
                      if (s === UserFileStatus.UPLOADING) return "Uploading...";
                      if (s === UserFileStatus.DELETING) return "Deleting...";
                      if (s === UserFileStatus.COMPLETED) return typeLabel;
                      return f.status ? f.status : typeLabel;
                    })()}
                  </Text>
                </div>
              </div>
              <div className="flex items-center gap-2">
                {f.last_accessed_at && (
                  <Text text03 secondaryBody nowrap>
                    {formatRelativeTime(f.last_accessed_at)}
                  </Text>
                )}
                {!showRemove && <div className="p-spacing-inline"></div>}
                {showRemove &&
                  String(f.status) !== UserFileStatus.UPLOADING &&
                  String(f.status) !== UserFileStatus.DELETING && (
                    <IconButton
                      internal
                      icon={SvgTrash}
                      tooltip="Remove from project"
                      className="opacity-0 group-hover:opacity-100 focus:opacity-100 transition-opacity duration-150 p-0 bg-transparent hover:bg-transparent shrink-0"
                      onClick={(e) => {
                        e.stopPropagation();
                        onRemove && onRemove(f);
                      }}
                    />
                  )}
              </div>
            </div>
          ))}
          {filtered.length === 0 && (
            <Text text03 secondaryBody className="px-2 py-4">
              No files found.
            </Text>
          )}
        </ScrollArea>
        {/* Fade effect at bottom when scrollable */}
        {isScrollable && (
          <div className="absolute bottom-0 left-0 right-0 h-16 bg-gradient-to-t from-background via-background/90 to-transparent pointer-events-none z-10 rounded-b-12" />
        )}
      </div>
    </>
  );
}
