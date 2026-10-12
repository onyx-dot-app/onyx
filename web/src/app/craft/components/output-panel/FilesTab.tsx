"use client";

import {
  useState,
  useEffect,
  useEffectEvent,
  useMemo,
  useRef,
  useCallback,
} from "react";
import { useUser } from "@/providers/UserProvider";
import { useTranslations } from "next-intl";
import {
  useBuildSessionStore,
  useFilesTabState,
} from "@/app/craft/hooks/useBuildSessionStore";
import { Text } from "@opal/components";
import { SvgHardDrive } from "@opal/icons";
import {
  DirectoryTree,
  type DirectoryStatus,
} from "@/app/craft/components/output-panel/DirectoryTree";
import { Section } from "@/layouts/general-layouts";
import { WorkspaceSearch } from "@/app/craft/components/output-panel/WorkspaceSearch";

interface FilesTabProps {
  sessionId: string | null;
  searchQuery?: string;
  onFileClick?: (path: string, fileName: string) => void;
  onRefreshingChange?: (isRefreshing: boolean) => void;
  refreshKey?: number;
  isProvisioning?: boolean;
  isActive?: boolean;
  canLoad?: boolean;
}

export default function FilesTab(props: FilesTabProps) {
  const { user } = useUser();
  return (
    <WorkspaceBrowser
      key={JSON.stringify([user?.id, props.sessionId])}
      {...props}
    />
  );
}

function WorkspaceBrowser({
  sessionId,
  onFileClick,
  onRefreshingChange,
  refreshKey = 0,
  searchQuery = "",
  isProvisioning = false,
  isActive = true,
  canLoad = isActive,
}: FilesTabProps) {
  const t = useTranslations("craft.filesTab");
  const filesTabState = useFilesTabState(sessionId);
  const refreshGeneration = useBuildSessionStore((state) =>
    sessionId ? (state.sessions.get(sessionId)?.filesNeedsRefresh ?? 0) : 0
  );
  const updateFilesTabState = useBuildSessionStore(
    (state) => state.updateFilesTabState
  );
  const expandedPaths = useMemo(
    () => new Set(filesTabState.expandedPaths),
    [filesTabState.expandedPaths]
  );
  const [loading] = useState(() => new DirectoryLoading());
  const onStatusChange = useCallback(
    (path: string, status: DirectoryStatus | undefined) =>
      loading.set(path, status),
    [loading]
  );
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
  const pendingScrollRestore = useRef(true);
  const restoreScroll = useCallback(() => {
    if (
      !listingReadyRef.current ||
      !pendingScrollRestore.current ||
      !scrollContainerRef.current ||
      !sessionId
    )
      return;
    scrollTopRef.current =
      useBuildSessionStore.getState().sessions.get(sessionId)?.filesTabState
        .scrollTop ?? 0;
    scrollContainerRef.current.scrollTop = scrollTopRef.current;
    if (!loading.isLoading) pendingScrollRestore.current = false;
  }, [loading, sessionId]);
  const onListingReady = useCallback(() => {
    listingReadyRef.current = true;
    pendingScrollRestore.current = true;
    restoreScroll();
  }, [restoreScroll]);
  const reportLoading = useEffectEvent((busy: boolean) => {
    if (!searchQuery.trim()) onRefreshingChange?.(isActive && busy);
    if (!busy) restoreScroll();
  });
  useEffect(() => loading.subscribe((busy) => reportLoading(busy)), [loading]);
  useEffect(() => {
    reportLoading(loading.isLoading);
  }, [loading, isActive, searchQuery, onRefreshingChange]);
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
    (path: string, fileName: string) => {
      saveScroll();
      onFileClick?.(path, fileName);
    },
    [onFileClick, saveScroll]
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
  return (
    <div className="flex flex-col h-full min-h-0">
      {searchQuery.trim() && (
        <WorkspaceSearch
          sessionId={sessionId}
          query={searchQuery}
          refreshKey={refreshKey + refreshGeneration}
          onFileClick={handleFileClick}
          onRefreshingChange={onRefreshingChange}
          isActive={isActive}
        />
      )}
      <div
        className={
          searchQuery.trim() ? "hidden" : "flex-1 min-h-0 flex flex-col"
        }
      >
        <div
          ref={setScrollContainer}
          onScroll={(event) => {
            scrollTopRef.current = event.currentTarget.scrollTop;
            pendingScrollRestore.current = false;
          }}
          className="flex-1 min-h-0 overflow-auto px-2 pb-2 relative"
        >
          <div className="sticky top-0 start-0 end-0 h-2 bg-background-neutral-00 -mx-2 z-101" />
          <div className="font-mono text-sm">
            <DirectoryTree
              sessionId={sessionId}
              path=""
              onReady={onListingReady}
              depth={0}
              isActive={canLoad && !searchQuery.trim()}
              refreshGeneration={refreshGeneration + refreshKey}
              onStatusChange={onStatusChange}
              expandedPaths={expandedPaths}
              onToggleFolder={toggleFolder}
              onFileClick={handleFileClick}
            />
          </div>
        </div>
      </div>
    </div>
  );
}

/** Coordinates request lifetimes without copying child loading state into React state. */
class DirectoryLoading {
  private paths = new Set<string>();
  private listener: ((loading: boolean) => void) | undefined;
  get isLoading() {
    return this.paths.size > 0;
  }
  set(path: string, status: DirectoryStatus | undefined) {
    const before = this.isLoading;
    if (status === "loading") this.paths.add(path);
    else this.paths.delete(path);
    if (before !== this.isLoading) this.listener?.(this.isLoading);
  }
  subscribe(listener: (loading: boolean) => void) {
    this.listener = listener;
    listener(this.isLoading);
    return () => {
      if (this.listener === listener) this.listener = undefined;
      listener(false);
    };
  }
}
