"use client";

import { useState, useEffect, useMemo, useRef, useCallback } from "react";
import useSWR from "swr";
import {
  useBuildSessionStore,
  useFilesTabState,
  useFilesNeedsRefresh,
} from "@/app/craft/hooks/useBuildSessionStore";
import { fetchDirectoryListing } from "@/app/craft/services/apiServices";
import { FileSystemEntry } from "@/app/craft/types/streamingTypes";
import { cn, getFileIcon } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import {
  SvgHardDrive,
  SvgFolder,
  SvgFolderOpen,
  SvgChevronRight,
  SvgArrowLeft,
  SvgImage,
  SvgFileText,
} from "@opal/icons";
import { Section } from "@/layouts/general-layouts";
import { InlineFilePreview } from "@/app/craft/components/output-panel/FilePreviewContent";

interface FilesTabProps {
  sessionId: string | null;
  onFileClick?: (path: string, fileName: string) => void;
  /** True when showing pre-provisioned sandbox (read-only, no file clicks) */
  isPreProvisioned?: boolean;
  /** True when sandbox is still being provisioned */
  isProvisioning?: boolean;
}

export default function FilesTab({
  sessionId,
  onFileClick,
  isPreProvisioned = false,
  isProvisioning = false,
}: FilesTabProps) {
  // Get persisted state from store (only used when not pre-provisioned)
  const filesTabState = useFilesTabState();
  const updateFilesTabState = useBuildSessionStore(
    (state) => state.updateFilesTabState
  );

  // Local state for pre-provisioned mode (no persistence needed)
  const [localExpandedPaths, setLocalExpandedPaths] = useState<Set<string>>(
    new Set()
  );
  const [localDirectoryCache, setLocalDirectoryCache] = useState<
    Map<string, FileSystemEntry[]>
  >(new Map());
  const [previewingFile, setPreviewingFile] = useState<{
    path: string;
    fileName: string;
    mimeType: string | null;
  } | null>(null);

  // Use local state for pre-provisioned, store state otherwise
  const expandedPaths = useMemo(
    () =>
      isPreProvisioned
        ? localExpandedPaths
        : new Set(filesTabState.expandedPaths),
    [isPreProvisioned, localExpandedPaths, filesTabState.expandedPaths]
  );

  const directoryCache = useMemo(
    () =>
      isPreProvisioned
        ? localDirectoryCache
        : (new Map(Object.entries(filesTabState.directoryCache)) as Map<
            string,
            FileSystemEntry[]
          >),
    [isPreProvisioned, localDirectoryCache, filesTabState.directoryCache]
  );

  // Scroll container ref for position tracking
  const scrollContainerRef = useRef<HTMLDivElement>(null);

  // Fetch root directory
  const {
    data: rootListing,
    error,
    mutate,
  } = useSWR(
    sessionId ? `/api/build/sessions/${sessionId}/files?path=` : null,
    () => (sessionId ? fetchDirectoryListing(sessionId, "") : null),
    {
      revalidateOnFocus: false,
      dedupingInterval: 2000,
    }
  );

  // Refresh files list when outputs/ directory changes
  const filesNeedsRefresh = useFilesNeedsRefresh();

  // Snapshot of currently expanded paths — avoids putting both local and store
  // versions in the dependency array (only one is used per mode).
  const currentExpandedPaths = isPreProvisioned
    ? Array.from(localExpandedPaths)
    : filesTabState.expandedPaths;

  useEffect(() => {
    if (filesNeedsRefresh > 0 && sessionId && mutate) {
      // Clear directory cache to ensure all directories are refreshed
      if (isPreProvisioned) {
        setLocalDirectoryCache(new Map());
      } else {
        updateFilesTabState(sessionId, { directoryCache: {} });
      }
      // Refresh root directory listing
      mutate();

      // Re-fetch all currently expanded subdirectories so they don't get
      // stuck on "Loading..." after the cache was cleared
      if (currentExpandedPaths.length > 0) {
        Promise.allSettled(
          currentExpandedPaths.map((p) => fetchDirectoryListing(sessionId, p))
        ).then((settled) => {
          // Collect only the successful fetches into a path → entries map
          const fetched = new Map<string, FileSystemEntry[]>();
          settled.forEach((r, i) => {
            const p = currentExpandedPaths[i];
            if (p && r.status === "fulfilled" && r.value) {
              fetched.set(p, r.value.entries);
            }
          });

          if (isPreProvisioned) {
            setLocalDirectoryCache((prev) => {
              const next = new Map(prev);
              fetched.forEach((entries, p) => next.set(p, entries));
              return next;
            });
          } else {
            const obj: Record<string, FileSystemEntry[]> = {};
            fetched.forEach((entries, p) => {
              obj[p] = entries;
            });
            updateFilesTabState(sessionId, { directoryCache: obj });
          }
        });
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    filesNeedsRefresh,
    sessionId,
    mutate,
    isPreProvisioned,
    updateFilesTabState,
  ]);

  // Update cache when root listing changes
  useEffect(() => {
    if (rootListing && sessionId) {
      if (isPreProvisioned) {
        setLocalDirectoryCache((prev) => {
          const newCache = new Map(prev);
          newCache.set("", rootListing.entries);
          return newCache;
        });
      } else {
        const newCache = {
          ...filesTabState.directoryCache,
          "": rootListing.entries,
        };
        updateFilesTabState(sessionId, { directoryCache: newCache });
      }
    }
  }, [rootListing, sessionId, isPreProvisioned]);

  const toggleFolder = useCallback(
    async (path: string) => {
      if (!sessionId) return;

      if (isPreProvisioned) {
        // Use local state for pre-provisioned mode
        const newExpanded = new Set(localExpandedPaths);
        if (newExpanded.has(path)) {
          newExpanded.delete(path);
          setLocalExpandedPaths(newExpanded);
        } else {
          newExpanded.add(path);
          if (!localDirectoryCache.has(path)) {
            const listing = await fetchDirectoryListing(sessionId, path);
            if (listing) {
              setLocalDirectoryCache((prev) => {
                const newCache = new Map(prev);
                newCache.set(path, listing.entries);
                return newCache;
              });
            }
          }
          setLocalExpandedPaths(newExpanded);
        }
      } else {
        // Use store state for active sessions
        const newExpanded = new Set(expandedPaths);
        if (newExpanded.has(path)) {
          newExpanded.delete(path);
          updateFilesTabState(sessionId, {
            expandedPaths: Array.from(newExpanded),
          });
        } else {
          newExpanded.add(path);
          if (!directoryCache.has(path)) {
            const listing = await fetchDirectoryListing(sessionId, path);
            if (listing) {
              const newCache = {
                ...filesTabState.directoryCache,
                [path]: listing.entries,
              };
              updateFilesTabState(sessionId, {
                expandedPaths: Array.from(newExpanded),
                directoryCache: newCache,
              });
              return;
            }
          }
          updateFilesTabState(sessionId, {
            expandedPaths: Array.from(newExpanded),
          });
        }
      }
    },
    [
      sessionId,
      isPreProvisioned,
      localExpandedPaths,
      localDirectoryCache,
      expandedPaths,
      directoryCache,
      filesTabState.directoryCache,
      updateFilesTabState,
    ]
  );

  // Handle file click for pre-provisioned mode (inline preview)
  const handleLocalFileClick = useCallback(
    (path: string, fileName: string, mimeType: string | null) => {
      if (isPreProvisioned) {
        setPreviewingFile({ path, fileName, mimeType });
      } else if (onFileClick) {
        onFileClick(path, fileName);
      }
    },
    [isPreProvisioned, onFileClick]
  );

  // Restore scroll position when component mounts or tab becomes active
  useEffect(() => {
    if (
      scrollContainerRef.current &&
      filesTabState.scrollTop > 0 &&
      !isPreProvisioned
    ) {
      scrollContainerRef.current.scrollTop = filesTabState.scrollTop;
    }
  }, []); // Only on mount

  // Save scroll position on scroll (debounced via passive listener)
  const handleScroll = useCallback(() => {
    if (scrollContainerRef.current && sessionId && !isPreProvisioned) {
      const scrollTop = scrollContainerRef.current.scrollTop;
      updateFilesTabState(sessionId, { scrollTop });
    }
  }, [sessionId, isPreProvisioned, updateFilesTabState]);

  const formatFileSize = (bytes: number | null): string => {
    if (bytes === null) return "";
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  if (!sessionId) {
    return (
      <Section
        height="full"
        alignItems="center"
        justifyContent="center"
        padding={2}
      >
        <SvgHardDrive size={48} className="stroke-text-02" />
        <Text headingH3 text03>
          {isProvisioning ? "Preparing sandbox..." : "No files yet"}
        </Text>
        <Text secondaryBody text02>
          {isProvisioning
            ? "Setting up your development environment"
            : "Files created during the build will appear here"}
        </Text>
      </Section>
    );
  }

  if (error) {
    return (
      <Section
        height="full"
        alignItems="center"
        justifyContent="center"
        padding={2}
      >
        <SvgHardDrive size={48} className="stroke-text-02" />
        <Text headingH3 text03>
          Error loading files
        </Text>
        <Text secondaryBody text02>
          {error.message}
        </Text>
      </Section>
    );
  }

  if (!rootListing) {
    return (
      <Section
        height="full"
        alignItems="center"
        justifyContent="center"
        padding={2}
      >
        <Text secondaryBody text03>
          Loading files...
        </Text>
      </Section>
    );
  }

  // Show inline file preview for pre-provisioned mode
  if (isPreProvisioned && previewingFile && sessionId) {
    const isImage = previewingFile.mimeType?.startsWith("image/");

    return (
      <div className="flex flex-col h-full">
        {/* Header with back button */}
        <div className="flex items-center gap-2 px-3 py-2 border-b border-border-01">
          <button
            onClick={() => setPreviewingFile(null)}
            className="p-1 rounded hover:bg-background-tint-02 transition-colors"
          >
            <SvgArrowLeft size={16} className="stroke-text-03" />
          </button>
          {isImage ? (
            <SvgImage size={16} className="stroke-text-03" />
          ) : (
            <SvgFileText size={16} className="stroke-text-03" />
          )}
          <Text secondaryBody text04 className="truncate">
            {previewingFile.fileName}
          </Text>
        </div>
        {/* File content */}
        <div className="flex-1 overflow-auto">
          <InlineFilePreview
            sessionId={sessionId}
            filePath={previewingFile.path}
          />
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      <div
        ref={scrollContainerRef}
        onScroll={handleScroll}
        className="flex-1 overflow-auto px-2 pb-2 relative"
      >
        {/* Background to prevent content showing through sticky gap */}
        <div className="sticky top-0 left-0 right-0 h-2 bg-background-neutral-00 -mx-2 z-[101]" />
        {rootListing.entries.length === 0 ? (
          <Section
            height="full"
            alignItems="center"
            justifyContent="center"
            padding={2}
          >
            <Text secondaryBody text03>
              No files in this directory
            </Text>
          </Section>
        ) : (
          <div className="font-mono text-sm">
            <FileTreeNode
              entries={rootListing.entries}
              depth={0}
              expandedPaths={expandedPaths}
              directoryCache={directoryCache}
              onToggleFolder={toggleFolder}
              onFileClick={handleLocalFileClick}
              formatFileSize={formatFileSize}
            />
          </div>
        )}
      </div>
    </div>
  );
}

// ── FileTreeNode (internal) ──────────────────────────────────────────────

interface FileTreeNodeProps {
  entries: FileSystemEntry[];
  depth: number;
  expandedPaths: Set<string>;
  directoryCache: Map<string, FileSystemEntry[]>;
  onToggleFolder: (path: string) => void;
  onFileClick?: (
    path: string,
    fileName: string,
    mimeType: string | null
  ) => void;
  formatFileSize: (bytes: number | null) => string;
  parentIsLast?: boolean[];
}

function FileTreeNode({
  entries,
  depth,
  expandedPaths,
  directoryCache,
  onToggleFolder,
  onFileClick,
  formatFileSize,
  parentIsLast = [],
}: FileTreeNodeProps) {
  // Sort entries: directories first, then alphabetically
  const sortedEntries = [...entries].sort((a, b) => {
    if (a.is_directory && !b.is_directory) return -1;
    if (!a.is_directory && b.is_directory) return 1;
    return a.name.localeCompare(b.name);
  });

  return (
    <>
      {sortedEntries.map((entry, index) => {
        const isExpanded = expandedPaths.has(entry.path);
        const isLast = index === sortedEntries.length - 1;
        const childEntries = directoryCache.get(entry.path) || [];
        const FileIcon = getFileIcon(entry.name);

        // Row height for sticky offset calculation
        const rowHeight = 28;
        // Account for the 8px (h-2) spacer at top of scroll container
        const stickyTopOffset = 8;

        return (
          <div key={entry.path} className="relative">
            {/* Tree item row */}
            <button
              onClick={() => {
                if (entry.is_directory) {
                  onToggleFolder(entry.path);
                } else if (onFileClick) {
                  onFileClick(entry.path, entry.name, entry.mime_type);
                }
              }}
              className={cn(
                "w-full flex items-center py-1.5 hover:bg-background-tint-02 rounded transition-colors relative",
                !entry.is_directory && onFileClick && "cursor-pointer",
                !entry.is_directory && !onFileClick && "cursor-default",
                // Make expanded folders sticky
                entry.is_directory &&
                  isExpanded &&
                  "sticky bg-background-neutral-00"
              )}
              style={
                entry.is_directory && isExpanded
                  ? {
                      top: stickyTopOffset + depth * rowHeight,
                      zIndex: 100 - depth, // Higher z-index for parent folders
                    }
                  : undefined
              }
            >
              {/* Tree lines for depth */}
              {parentIsLast.map((isParentLast, i) => (
                <span
                  key={i}
                  className="inline-flex w-5 justify-center flex-shrink-0 self-stretch relative"
                >
                  {!isParentLast && (
                    <span className="absolute left-1/2 -translate-x-1/2 -top-1.5 -bottom-1.5 w-px bg-border-02" />
                  )}
                </span>
              ))}

              {/* Branch connector */}
              {depth > 0 && (
                <span className="inline-flex w-5 flex-shrink-0 self-stretch relative">
                  {/* Vertical line */}
                  <span
                    className={cn(
                      "absolute left-1/2 -translate-x-1/2 w-px bg-border-02",
                      isLast ? "-top-1.5 bottom-1/2" : "-top-1.5 -bottom-1.5"
                    )}
                  />
                  {/* Horizontal line */}
                  <span className="absolute top-1/2 left-1/2 w-2 h-px bg-border-02" />
                </span>
              )}

              {/* Expand/collapse chevron for directories */}
              {entry.is_directory ? (
                <span className="inline-flex w-4 h-4 items-center justify-center flex-shrink-0">
                  <SvgChevronRight
                    size={12}
                    className={cn(
                      "stroke-text-03 transition-transform duration-150",
                      isExpanded && "rotate-90"
                    )}
                  />
                </span>
              ) : (
                <span className="w-4 flex-shrink-0" />
              )}

              {/* Icon */}
              {entry.is_directory ? (
                isExpanded ? (
                  <SvgFolderOpen
                    size={16}
                    className="stroke-text-03 flex-shrink-0 mx-1"
                  />
                ) : (
                  <SvgFolder
                    size={16}
                    className="stroke-text-03 flex-shrink-0 mx-1"
                  />
                )
              ) : (
                <FileIcon
                  size={16}
                  className="stroke-text-03 flex-shrink-0 mx-1"
                />
              )}

              {/* Name */}
              <Text
                secondaryBody
                text04
                className="truncate flex-1 text-left ml-1"
              >
                {entry.name}
              </Text>

              {/* File size */}
              {!entry.is_directory && entry.size !== null && (
                <Text text02 className="ml-2 mr-2 flex-shrink-0">
                  {formatFileSize(entry.size)}
                </Text>
              )}
            </button>

            {/* Render children if expanded */}
            {entry.is_directory && isExpanded && childEntries.length > 0 && (
              <FileTreeNode
                entries={childEntries}
                depth={depth + 1}
                expandedPaths={expandedPaths}
                directoryCache={directoryCache}
                onToggleFolder={onToggleFolder}
                onFileClick={onFileClick}
                formatFileSize={formatFileSize}
                parentIsLast={[...parentIsLast, isLast]}
              />
            )}

            {/* Loading indicator for expanded but not-yet-loaded directories */}
            {entry.is_directory &&
              isExpanded &&
              !directoryCache.has(entry.path) && (
                <div
                  className="flex items-center py-1"
                  style={{ paddingLeft: `${(depth + 1) * 20 + 24}px` }}
                >
                  <Text secondaryBody text02>
                    Loading...
                  </Text>
                </div>
              )}
          </div>
        );
      })}
    </>
  );
}
