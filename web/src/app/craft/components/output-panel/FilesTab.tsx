"use client";

import { useState, useEffect, useMemo, useRef, useCallback } from "react";
import { useTranslations } from "next-intl";
import useSWR, { SWRConfig } from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  useBuildSessionStore,
  useFilesTabState,
} from "@/app/craft/hooks/useBuildSessionStore";
import {
  downloadArtifactFile,
  fetchDirectoryListing,
} from "@/app/craft/services/apiServices";
import type { DirectoryListing } from "@/app/craft/types/streamingTypes";
import { getFileIcon, formatBytes } from "@/lib/utils";
import { cn } from "@opal/utils";
import { Button, Text } from "@opal/components";
import {
  SvgHardDrive,
  SvgFolder,
  SvgFolderOpen,
  SvgChevronRight,
  SvgArrowLeft,
  SvgDownload,
  SvgImage,
  SvgFileText,
  SvgLoader,
  SvgAlertCircle,
} from "@opal/icons";
import { Section } from "@/layouts/general-layouts";
import { FilePreviewContent } from "@/app/craft/components/output-panel/FilePreviewContent";

interface FilesTabProps {
  sessionId: string | null;
  onFileClick?: (path: string, fileName: string) => void;
  onRefreshingChange?: (isRefreshing: boolean) => void;
  /** Explicit toolbar reloads also refresh welcome-page inline previews. */
  refreshKey?: number;
  /** Welcome sessions use an inline preview until the first message starts. */
  isPreProvisioned?: boolean;
  isProvisioning?: boolean;
  isActive?: boolean;
}

export default function FilesTab(props: FilesTabProps) {
  // Directory data lives only as long as this retained workspace browser.
  return (
    <SWRConfig key={props.sessionId} value={{ provider: () => new Map() }}>
      <WorkspaceBrowser {...props} />
    </SWRConfig>
  );
}

function WorkspaceBrowser({
  sessionId,
  onFileClick,
  onRefreshingChange,
  refreshKey = 0,
  isPreProvisioned = false,
  isProvisioning = false,
  isActive = true,
}: FilesTabProps) {
  const t = useTranslations("craft.filesTab");
  const toolbarTranslations = useTranslations("craft.urlBar");
  const filesTabState = useFilesTabState(sessionId);
  const refreshGeneration = useBuildSessionStore((state) =>
    sessionId ? (state.sessions.get(sessionId)?.filesNeedsRefresh ?? 0) : 0
  );
  const updateFilesTabState = useBuildSessionStore(
    (state) => state.updateFilesTabState
  );
  const [previewingFile, setPreviewingFile] = useState<{
    path: string;
    fileName: string;
    mimeType: string | null;
  } | null>(null);
  const previewRefreshKey = useBuildSessionStore((state) =>
    sessionId && previewingFile
      ? (state.sessions.get(sessionId)?.filePreviewRefreshKeys[
          previewingFile.path
        ] ?? 0)
      : 0
  );
  const previewRevision = useBuildSessionStore((state) =>
    sessionId && previewingFile
      ? state.sessions.get(sessionId)?.outputInventory?.[previewingFile.path]
          ?.revision
      : undefined
  );
  const expandedPaths = useMemo(
    () => new Set(filesTabState.expandedPaths),
    [filesTabState.expandedPaths]
  );
  const [directoryStatuses, setDirectoryStatuses] = useState<
    Map<string, DirectoryStatus>
  >(() => new Map());
  const onStatusChange = useCallback(
    (path: string, status: DirectoryStatus | undefined) => {
      setDirectoryStatuses((statuses) => {
        if (statuses.get(path) === status) return statuses;
        const next = new Map(statuses);
        if (status) next.set(path, status);
        else next.delete(path);
        return next;
      });
    },
    []
  );
  const isLoading = [...directoryStatuses.values()].includes("loading");
  useEffect(() => {
    onRefreshingChange?.(isActive && isLoading);
  }, [onRefreshingChange, isActive, isLoading]);
  useEffect(() => () => onRefreshingChange?.(false), [onRefreshingChange]);
  useEffect(() => {
    // Inline previews show their own loading state instead of directory progress.
    if (previewingFile) onRefreshingChange?.(false);
  }, [previewingFile, refreshKey, onRefreshingChange]);

  const toggleFolder = useCallback(
    (path: string) => {
      if (!sessionId) return;
      const paths = new Set(
        useBuildSessionStore.getState().sessions.get(sessionId)?.filesTabState
          .expandedPaths
      );
      if (paths.has(path)) paths.delete(path);
      else paths.add(path);
      updateFilesTabState(sessionId, { expandedPaths: [...paths] });
    },
    [sessionId, updateFilesTabState]
  );

  const scrollContainerRef = useRef<HTMLDivElement | null>(null);
  const listingReadyRef = useRef(false);
  const scrollTopRef = useRef(filesTabState.scrollTop);
  const saveScroll = useCallback(() => {
    if (sessionId && scrollContainerRef.current && listingReadyRef.current) {
      updateFilesTabState(sessionId, {
        scrollTop: scrollTopRef.current,
      });
    }
  }, [sessionId, updateFilesTabState]);
  const [listingMount, setListingMount] = useState(0);
  const restoredListingRef = useRef(0);
  const onListingReady = useCallback(() => {
    listingReadyRef.current = true;
    if (scrollContainerRef.current && sessionId) {
      scrollTopRef.current =
        useBuildSessionStore.getState().sessions.get(sessionId)?.filesTabState
          .scrollTop ?? 0;
      scrollContainerRef.current.scrollTop = scrollTopRef.current;
    }
    setListingMount((mount) => mount + 1);
  }, [sessionId]);
  useEffect(() => {
    if (isLoading || restoredListingRef.current === listingMount) return;
    if (scrollContainerRef.current && sessionId) {
      scrollTopRef.current =
        useBuildSessionStore.getState().sessions.get(sessionId)?.filesTabState
          .scrollTop ?? 0;
      scrollContainerRef.current.scrollTop = scrollTopRef.current;
      restoredListingRef.current = listingMount;
    }
  }, [listingMount, isLoading, sessionId]);
  const setScrollContainer = useCallback(
    (container: HTMLDivElement | null) => {
      if (!container) saveScroll();
      scrollContainerRef.current = container;
    },
    [saveScroll]
  );
  useEffect(() => {
    if (!isActive) saveScroll();
  }, [isActive, saveScroll]);

  const handleFileClick = useCallback(
    (path: string, fileName: string, mimeType: string | null) => {
      saveScroll();
      if (isPreProvisioned) setPreviewingFile({ path, fileName, mimeType });
      else onFileClick?.(path, fileName);
    },
    [isPreProvisioned, onFileClick, saveScroll]
  );

  if (!sessionId) {
    return (
      <Section
        height="full"
        alignItems="center"
        justifyContent="center"
        padding={8}
      >
        <SvgHardDrive size={48} className="stroke-text-02" />
        <Text font="heading-h3" color="text-03">
          {isProvisioning ? t("preparing.title") : t("empty.title")}
        </Text>
        <Text font="secondary-body" color="text-02">
          {isProvisioning ? t("preparing.description") : t("empty.description")}
        </Text>
      </Section>
    );
  }
  if (previewingFile) {
    const isImage = previewingFile.mimeType?.startsWith("image/");
    return (
      <div className="flex flex-col h-full">
        <div className="flex items-center gap-2 px-3 py-2 border-b border-border-01">
          <Button
            icon={SvgArrowLeft}
            prominence="tertiary"
            size="sm"
            onClick={() => setPreviewingFile(null)}
          />
          {isImage ? (
            <SvgImage size={16} className="stroke-text-03" />
          ) : (
            <SvgFileText size={16} className="stroke-text-03" />
          )}
          <Text font="secondary-body" color="text-04" maxLines={1}>
            {previewingFile.fileName}
          </Text>
          <Button
            icon={SvgDownload}
            prominence="tertiary"
            size="sm"
            tooltip={toolbarTranslations("downloadFile.tooltip")}
            aria-label={toolbarTranslations("downloadFile.tooltip")}
            onClick={() => downloadArtifactFile(sessionId, previewingFile.path)}
          />
        </div>
        <div className="flex-1 overflow-auto">
          <FilePreviewContent
            isActive={isActive}
            fullHeight={false}
            sessionId={sessionId}
            filePath={previewingFile.path}
            revision={previewRevision}
            refreshKey={previewRefreshKey + refreshKey}
          />
        </div>
      </div>
    );
  }
  return (
    <div
      ref={setScrollContainer}
      onScroll={(event) => {
        scrollTopRef.current = event.currentTarget.scrollTop;
        restoredListingRef.current = listingMount;
      }}
      className="flex-1 h-full overflow-auto px-2 pb-2 relative"
    >
      <div className="sticky top-0 start-0 end-0 h-2 bg-background-neutral-00 -mx-2 z-101" />
      <div className="font-mono text-sm">
        <DirectoryTree
          sessionId={sessionId}
          path=""
          onReady={onListingReady}
          depth={0}
          isActive={isActive}
          refreshGeneration={refreshGeneration}
          onStatusChange={onStatusChange}
          directoryStatuses={directoryStatuses}
          expandedPaths={expandedPaths}
          onToggleFolder={toggleFolder}
          onFileClick={handleFileClick}
        />
      </div>
    </div>
  );
}

type DirectoryStatus = "loading" | "error";
const MIN_LOADING_ICON_MS = 150;

interface DirectoryTreeProps {
  sessionId: string;
  path: string;
  depth: number;
  isActive: boolean;
  refreshGeneration: number;
  onStatusChange: (path: string, status: DirectoryStatus | undefined) => void;
  directoryStatuses: Map<string, DirectoryStatus>;
  expandedPaths: Set<string>;
  onToggleFolder: (path: string) => void;
  onFileClick: (
    path: string,
    fileName: string,
    mimeType: string | null
  ) => void;
  parentIsLast?: boolean[];
  onReady?: () => void;
}

function DirectoryTree({
  sessionId,
  path,
  isActive,
  refreshGeneration,
  onStatusChange,
  directoryStatuses,
  depth,
  expandedPaths,
  onToggleFolder,
  onFileClick,
  parentIsLast = [],
  onReady,
}: DirectoryTreeProps) {
  const t = useTranslations("craft.filesTab");
  const requestRef = useRef<AbortController | null>(null);
  const loadingTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(
    undefined
  );
  const [isLoading, setIsLoading] = useState(false);
  const { data, error, mutate } = useSWR<DirectoryListing, Error>(
    [SWR_KEYS.buildSessionFiles(sessionId), path],
    async () => {
      requestRef.current?.abort();
      clearTimeout(loadingTimerRef.current);
      const controller = new AbortController();
      requestRef.current = controller;
      const startedAt = Date.now();
      setIsLoading(true);
      try {
        return await fetchDirectoryListing(sessionId, path, controller.signal);
      } finally {
        if (requestRef.current === controller) {
          // Keep the icon steady without delaying the directory contents.
          const remaining = MIN_LOADING_ICON_MS - (Date.now() - startedAt);
          if (remaining > 0) {
            loadingTimerRef.current = setTimeout(
              () => setIsLoading(false),
              remaining
            );
          } else {
            setIsLoading(false);
          }
        }
      }
    },
    {
      revalidateOnMount: false,
      revalidateOnFocus: false,
      revalidateOnReconnect: false,
      shouldRetryOnError: false,
      isPaused: () => !isActive,
    }
  );

  // Each visible directory owns its request. SWR rejects superseded results.
  useEffect(() => {
    if (isActive) void mutate().catch(() => undefined);
    return () => {
      requestRef.current?.abort();
      requestRef.current = null;
      clearTimeout(loadingTimerRef.current);
    };
  }, [isActive, refreshGeneration, mutate]);

  const failed = error && error.name !== "AbortError" && !isLoading;
  const status = !isActive
    ? undefined
    : isLoading
      ? "loading"
      : failed
        ? "error"
        : undefined;
  useEffect(() => {
    onStatusChange(path, status);
    return () => onStatusChange(path, undefined);
  }, [path, status, onStatusChange]);

  const hasData = data !== undefined;
  useEffect(() => {
    if (hasData) onReady?.();
  }, [hasData, onReady]);

  if (!data) {
    if (path) return null;
    return (
      <div className="px-3 py-2" role={failed ? "alert" : "status"}>
        <Text font="secondary-body" color="text-03">
          {failed ? t("error.title") : t("loading.label")}
        </Text>
      </div>
    );
  }
  const entries = data.entries;
  // Sort entries: directories first, then alphabetically
  const sortedEntries = [...entries].sort((a, b) => {
    if (a.is_directory && !b.is_directory) return -1;
    if (!a.is_directory && b.is_directory) return 1;
    return a.name.localeCompare(b.name);
  });

  return (
    <>
      {!path && failed && <Text color="text-03">{t("error.title")}</Text>}
      {sortedEntries.map((entry, index) => {
        const isExpanded = expandedPaths.has(entry.path);
        const isLast = index === sortedEntries.length - 1;
        const FileIcon = getFileIcon(entry.name);
        const folderStatus = directoryStatuses.get(entry.path);
        const FolderIcon =
          folderStatus === "loading"
            ? SvgLoader
            : folderStatus === "error"
              ? SvgAlertCircle
              : isExpanded
                ? SvgFolderOpen
                : SvgFolder;

        // Row height for sticky offset calculation
        const rowHeight = 28;
        // Account for the 8px (h-2) spacer at top of scroll container
        const stickyTopOffset = 8;

        return (
          <div key={entry.path} className="relative">
            {/* Tree item row */}
            <button
              aria-expanded={entry.is_directory ? isExpanded : undefined}
              aria-busy={folderStatus === "loading" || undefined}
              title={folderStatus === "error" ? t("error.title") : undefined}
              onClick={() => {
                if (entry.is_directory) {
                  onToggleFolder(entry.path);
                } else {
                  onFileClick(entry.path, entry.name, entry.mime_type);
                }
              }}
              className={cn(
                "w-full flex items-center py-1.5 hover:bg-background-tint-02 rounded-sm transition-colors relative",
                !entry.is_directory && "cursor-pointer",
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
                  className="inline-flex w-5 justify-center shrink-0 self-stretch relative"
                >
                  {!isParentLast && (
                    <span className="absolute left-1/2 -translate-x-1/2 -top-1.5 -bottom-1.5 w-px bg-border-02" />
                  )}
                </span>
              ))}

              {/* Branch connector */}
              {depth > 0 && (
                <span className="inline-flex w-5 shrink-0 self-stretch relative">
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
                <span className="inline-flex w-4 h-4 items-center justify-center shrink-0">
                  <SvgChevronRight
                    size={12}
                    className={cn(
                      "stroke-text-03 transition-transform duration-150",
                      isExpanded && "rotate-90"
                    )}
                  />
                </span>
              ) : (
                <span className="w-4 shrink-0" />
              )}

              {entry.is_directory ? (
                <FolderIcon
                  size={16}
                  className={cn(
                    "text-text-03 shrink-0 mx-1",
                    folderStatus === "loading" && "animate-spin"
                  )}
                />
              ) : (
                <FileIcon size={16} className="text-text-03 shrink-0 mx-1" />
              )}

              {/* Name */}
              <span className="flex-1 text-start ms-1 min-w-0">
                <Text font="secondary-body" color="text-04" maxLines={1}>
                  {entry.name}
                </Text>
              </span>

              {/* File size */}
              {!entry.is_directory && entry.size !== null && (
                <span className="ms-2 me-2 shrink-0">
                  <Text color="text-02">{formatBytes(entry.size, 1)}</Text>
                </span>
              )}
            </button>

            {entry.is_directory && isExpanded && (
              <DirectoryTree
                sessionId={sessionId}
                path={entry.path}
                depth={depth + 1}
                isActive={isActive}
                refreshGeneration={refreshGeneration}
                onStatusChange={onStatusChange}
                directoryStatuses={directoryStatuses}
                expandedPaths={expandedPaths}
                onToggleFolder={onToggleFolder}
                onFileClick={onFileClick}
                parentIsLast={[...parentIsLast, isLast]}
              />
            )}
          </div>
        );
      })}
    </>
  );
}
