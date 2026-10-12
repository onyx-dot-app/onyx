"use client";

import { useUser } from "@/providers/UserProvider";
import { memo, useState, useEffect, useCallback, useRef } from "react";
import dynamic from "next/dynamic";
import { useTranslations } from "next-intl";
import { SelectCard, Text } from "@opal/components";
import { SvgFiles, SvgFolder, SvgGlobe } from "@opal/icons";
import { cn } from "@opal/utils";
import { downloadFile } from "@/lib/download";
import { useOutputWebapps } from "@/lib/build/hooks";
import {
  useOutputSession,
  useSessionId,
  usePanelTabs,
  useOutputWorkspaceId,
  useActivePanelTabId,
  usePreProvisionedSessionId,
  useIsPreProvisioning,
  useBuildSessionStore,
} from "@/app/craft/hooks/useBuildSessionStore";
import {
  panelTabId,
  type OutputPanelMode,
  type PanelTab,
} from "@/app/craft/types/displayTypes";
import {
  exportDocx,
  downloadArtifactFile,
} from "@/app/craft/services/apiServices";
import ResourceTabStrip, {
  resourcePanelDomId,
  resourceTabDomId,
} from "@/app/craft/components/output-panel/ResourceTabStrip";
import OutputsTab from "@/app/craft/components/output-panel/OutputsTab";
import BrowserTab from "@/app/craft/components/output-panel/BrowserTab";
import { WorkspaceUploadButton } from "@/app/craft/components/output-panel/WorkspaceUploadButton";
import UrlBar from "@/app/craft/components/output-panel/UrlBar";
import { WorkspaceHome } from "@/app/craft/components/output-panel/WorkspaceHome";

const FilesTab = dynamic(
  () => import("@/app/craft/components/output-panel/FilesTab"),
  { ssr: false }
);
const FilePreviewContent = dynamic(
  () =>
    import("@/app/craft/components/output-panel/FilePreviewContent").then(
      (module) => module.FilePreviewContent
    ),
  { ssr: false }
);

interface FileResourceViewState {
  slide: number;
  scrollTop: number;
}
interface TabResourceState extends FileResourceViewState {
  tab: PanelTab;
  mountKey: number;
  manualRefresh: boolean;
  refreshKey: number;
  pending: boolean;
  exportState: "pending" | "failed" | "idle";
}
const MAX_RETAINED_FILE_VIEWERS = 5;
const FILES_TAB: PanelTab = { kind: "files" };

function createResource(tab: PanelTab, mountKey = 0): TabResourceState {
  return {
    tab,
    mountKey,
    slide: 0,
    scrollTop: 0,
    refreshKey: 0,
    pending: false,
    manualRefresh: false,
    exportState: "idle",
  };
}

interface ResourceRegistry {
  tabs: PanelTab[];
  visitedId: string | null;
  visited: string[];
  entries: Record<string, TabResourceState>;
}

function reconcileResources(
  previous: ResourceRegistry | undefined,
  tabs: PanelTab[],
  visitedId: string | null
): ResourceRegistry {
  // Keep one directory browser warm for the workspace, even without an open Files tab.
  const resourceTabs = tabs.some((tab) => tab.kind === "files")
    ? tabs
    : [...tabs, previous?.entries.files?.tab ?? FILES_TAB];
  const entries = Object.fromEntries(
    resourceTabs.map((tab): [string, TabResourceState] => {
      const id = panelTabId(tab);
      const existing = previous?.entries[id];
      if (existing?.tab === tab) return [id, existing];
      if (existing && tab.kind === "files") return [id, { ...existing, tab }];
      // Browser navigation changes metadata; its unique tab ID owns the frame lifetime.
      if (existing && tab.kind === "browser")
        return [id, { ...existing, tab, pending: false, manualRefresh: false }];
      return [id, createResource(tab, (existing?.mountKey ?? -1) + 1)];
    })
  );
  const visited = (previous?.visited ?? []).filter(
    (id) => entries[id]?.tab.kind === "file"
  );
  return {
    tabs,
    visitedId,
    entries,
    visited: visitedId
      ? [...visited.filter((id) => id !== visitedId), visitedId].slice(
          -MAX_RETAINED_FILE_VIEWERS
        )
      : visited,
  };
}

interface BuildOutputPanelProps {
  panelMode: OutputPanelMode;
  headerControlWidth?: number;
}

function BuildOutputPanel(props: BuildOutputPanelProps) {
  const workspaceId = useOutputWorkspaceId();
  const { user } = useUser();
  return (
    <OutputResources key={JSON.stringify([user?.id, workspaceId])} {...props} />
  );
}

export default memo(BuildOutputPanel);

function OutputResources({
  panelMode,
  headerControlWidth = 0,
}: BuildOutputPanelProps) {
  const isOpen = panelMode !== "closed";
  const t = useTranslations("craft.outputWorkspace");
  const tabTranslations = useTranslations("craft.resourceTabs");
  const outputsTranslations = useTranslations("craft.outputsTab");
  const browserTranslations = useTranslations("craft.browserTab");
  const session = useOutputSession();
  const sessionId = useSessionId();
  const preProvisionedSessionId = usePreProvisionedSessionId();
  const isProvisioning = useIsPreProvisioning();
  const contentSessionId = sessionId ?? preProvisionedSessionId;
  const runtimeReady = sessionId
    ? session?.sandbox?.status === "running"
    : !!preProvisionedSessionId && !isProvisioning;
  const tabs = usePanelTabs();
  const activeId = useActivePanelTabId();
  const active = tabs.find((tab) => panelTabId(tab) === activeId);
  const select = useBuildSessionStore((state) => state.setActivePanelTabId);
  const close = useBuildSessionStore((state) => state.closePanelTab);
  const reorder = useBuildSessionStore((state) => state.reorderPanelTab);
  const openOutputs = useBuildSessionStore((state) => state.openOutputsTab);
  const outputInventoryLoading = useBuildSessionStore((state) =>
    contentSessionId
      ? state.sessions.get(contentSessionId)?.outputInventoryLoading
      : undefined
  );
  const openFiles = useBuildSessionStore((state) => state.openFilesTab);
  const openBrowser = useBuildSessionStore((state) => state.openBrowserTab);
  const navigateBrowser = useBuildSessionStore(
    (state) => state.navigateBrowserTab
  );
  const [search, setSearch] = useState("");
  const [outputsSearch, setOutputsSearch] = useState("");
  const visitedId = isOpen && active?.kind === "file" ? activeId : null;
  const [storedResources, setResources] = useState(() =>
    reconcileResources(undefined, tabs, visitedId)
  );
  // Reconcile before children render; replacement tabs start with fresh state.
  const resources =
    storedResources.tabs !== tabs || storedResources.visitedId !== visitedId
      ? reconcileResources(storedResources, tabs, visitedId)
      : storedResources;
  if (resources !== storedResources) setResources(resources);
  const { entries, visited } = resources;
  const activeResource = active ? entries[panelTabId(active)] : undefined;
  const exporting = activeResource?.exportState === "pending";
  const exportError = activeResource?.exportState === "failed";
  const scopeAlive = useRef(true);
  useEffect(() => {
    scopeAlive.current = true;
    return () => {
      scopeAlive.current = false;
    };
  }, []);
  const updateResource = useCallback(
    (
      tab: PanelTab,
      update: Partial<Omit<TabResourceState, "tab" | "mountKey">>
    ) => {
      if (!scopeAlive.current) return;
      const state = useBuildSessionStore.getState();
      const openTabs = state.currentSessionId
        ? state.sessions.get(state.currentSessionId)?.panelTabs
        : state.noSessionPanelTabs;
      // IDs can be reused after closing a file or collection. Match its lifetime too.
      if (!openTabs?.includes(tab)) return;
      const id = panelTabId(tab);
      setResources((previous) => {
        const current = previous.entries[id];
        if (!current || current.tab !== tab) return previous;
        const next = { ...current, ...update };
        if (
          current.slide === next.slide &&
          current.scrollTop === next.scrollTop &&
          current.refreshKey === next.refreshKey &&
          current.pending === next.pending &&
          current.manualRefresh === next.manualRefresh &&
          current.exportState === next.exportState
        )
          return previous;
        return { ...previous, entries: { ...previous.entries, [id]: next } };
      });
    },
    []
  );
  const onResourceLoading = useCallback(
    (tab: PanelTab, pending: boolean) =>
      updateResource(
        tab,
        pending ? { pending } : { pending, manualRefresh: false }
      ),
    [updateResource]
  );

  const {
    apps,
    accessRevoked,
    discoveryState,
    canQuery,
    runtimeUnavailable,
    webappInfo,
    webappChecking,
    refreshWebapps,
  } = useOutputWebapps({
    session,
    sessionId,
    isOpen,
    hasBrowser: tabs.some((tab) => tab.kind === "browser"),
    activeBrowser: active?.kind === "browser",
    appName: browserTranslations("localApp.label"),
  });
  const selectedApp =
    active?.kind === "browser"
      ? apps.find((app) => app.id === active.appId)
      : undefined;
  const refreshAllowed =
    active?.kind === "browser"
      ? canQuery && !accessRevoked
      : !!contentSessionId && runtimeReady && !accessRevoked;
  const refreshing =
    active?.kind === "outputs"
      ? !!outputInventoryLoading
      : (activeResource?.pending ?? false) ||
        (active?.kind === "browser" && webappChecking && !webappInfo?.ready);

  function refresh() {
    if (
      !active ||
      refreshing ||
      activeResource?.manualRefresh ||
      !refreshAllowed
    )
      return;
    const requestedTabId = panelTabId(active);
    updateResource(active, { manualRefresh: true });
    if (active.kind === "outputs" && contentSessionId) {
      select(sessionId, requestedTabId);
      const store = useBuildSessionStore.getState();
      const current = store.sessions.get(contentSessionId);
      void store
        .refreshOutputInventory(contentSessionId, {
          silent: !current?.activeTurnId && current?.status !== "running",
        })
        .finally(() => {
          if (scopeAlive.current)
            updateResource(active, { manualRefresh: false });
        });
    } else if (active.kind === "files") {
      updateResource(active, { pending: true });
      if (sessionId)
        useBuildSessionStore.getState().triggerFilesRefresh(sessionId);
      else
        updateResource(active, {
          refreshKey: (activeResource?.refreshKey ?? 0) + 1,
        });
    } else if (active.kind === "browser") {
      if (selectedApp?.state === "ready") {
        updateResource(active, {
          refreshKey: (activeResource?.refreshKey ?? 0) + 1,
        });
      } else {
        void refreshWebapps()
          .catch(() => undefined)
          .finally(() => {
            if (scopeAlive.current)
              updateResource(active, { manualRefresh: false });
          });
      }
    } else if (contentSessionId) {
      updateResource(active, {
        pending: true,
        refreshKey: (activeResource?.refreshKey ?? 0) + 1,
      });
    }
  }

  async function downloadDocx() {
    if (!sessionId || active?.kind !== "file" || exporting) return;
    const resource = active;
    const requestedSessionId = sessionId;
    const path = resource.path;
    function isCurrentResource() {
      return (
        scopeAlive.current &&
        useBuildSessionStore
          .getState()
          .sessions.get(requestedSessionId)
          ?.panelTabs.includes(resource)
      );
    }
    updateResource(resource, { exportState: "pending" });
    try {
      const blob = await exportDocx(sessionId, path);
      if (!isCurrentResource()) return;
      downloadFile(
        path.split("/").pop()?.replace(/\.md$/i, ".docx") ?? "document.docx",
        { content: blob }
      );
    } catch {
      if (isCurrentResource())
        updateResource(resource, { exportState: "failed" });
      return;
    }
    if (isCurrentResource()) updateResource(resource, { exportState: "idle" });
  }

  // Browser frames keep their DOM position. Only read-only viewers may be evicted.
  const mountedResources = (accessRevoked ? [] : Object.values(entries))
    .filter(
      ({ tab }) =>
        tab.kind !== "file" ||
        visited.includes(panelTabId(tab)) ||
        panelTabId(tab) === activeId
    )
    .toSorted((first, second) =>
      panelTabId(first.tab).localeCompare(panelTabId(second.tab))
    );
  return (
    <div className="flex h-full min-w-0 flex-col" data-testid="output-panel">
      <div
        className="flex h-[52px] shrink-0 items-center ps-3"
        style={{ paddingInlineEnd: headerControlWidth }}
      >
        <ResourceTabStrip
          tabs={tabs}
          activeTabId={activeId}
          onSelect={(id) => select(sessionId, id)}
          onClose={(id) => close(sessionId, id)}
          onReorder={(id, index) => reorder(sessionId, id, index)}
          onOpenOutputs={() => openOutputs(sessionId)}
          onOpenFiles={() => openFiles(sessionId)}
          onOpenBrowser={() => openBrowser(sessionId)}
          panelMode={panelMode}
        />
      </div>
      {active && (
        <UrlBar
          displayUrl={
            active.kind === "file"
              ? active.path
              : active.kind === "browser"
                ? (selectedApp?.url ?? t("browser.placeholder"))
                : active.kind === "outputs"
                  ? outputsTranslations("home.description")
                  : t("files.location.label")
          }
          searchValue={active.kind === "outputs" ? outputsSearch : search}
          onSearchChange={
            active.kind === "files"
              ? setSearch
              : active.kind === "outputs"
                ? setOutputsSearch
                : undefined
          }
          placeholder={
            active.kind === "outputs"
              ? outputsTranslations("search.placeholder")
              : t("files.search.placeholder")
          }
          refreshLabel={
            refreshAllowed
              ? t(
                  active.kind === "file"
                    ? "reload.file"
                    : active.kind === "files" || active.kind === "outputs"
                      ? "reload.files"
                      : "reload.browser"
                )
              : t("reload.unavailable")
          }
          onRefresh={refreshAllowed ? refresh : undefined}
          isRefreshing={refreshing}
          isUserRefreshing={activeResource?.manualRefresh ?? false}
          uploadAction={
            contentSessionId ? (
              <div hidden={active.kind !== "files"}>
                <WorkspaceUploadButton
                  key={contentSessionId}
                  sessionId={contentSessionId}
                  disabled={runtimeUnavailable || accessRevoked}
                />
              </div>
            ) : undefined
          }
          onDownloadRaw={
            !accessRevoked && active.kind === "file" && contentSessionId
              ? () => downloadArtifactFile(contentSessionId, active.path)
              : undefined
          }
          onDownload={
            !accessRevoked &&
            active.kind === "file" &&
            /\.md$/i.test(active.path)
              ? downloadDocx
              : undefined
          }
          isDownloading={exporting}
          previewUrl={accessRevoked ? undefined : selectedApp?.url}
          sessionId={selectedApp ? (sessionId ?? undefined) : undefined}
          sharingScope={webappInfo?.sharing_scope}
          onScopeChange={() => {
            void refreshWebapps().catch(() => undefined);
          }}
        />
      )}
      {exportError && (
        <div role="alert" className="px-3">
          <Text font="secondary-body" color="text-03">
            {t("export.failed")}
          </Text>
        </div>
      )}
      <div className="relative min-h-0 flex-1 overflow-hidden">
        {accessRevoked && (
          <div role="alert" className="p-4">
            <Text color="text-03">{t("reload.unavailable")}</Text>
          </div>
        )}
        {!active && (
          <WorkspaceHome title={t("empty.title")}>
            {[
              {
                label: tabTranslations("outputs.label"),
                icon: SvgFiles,
                onOpen: () => openOutputs(sessionId),
              },
              {
                label: tabTranslations("files.label"),
                icon: SvgFolder,
                onOpen: () => openFiles(sessionId),
              },
              {
                label: tabTranslations("browser.label"),
                icon: SvgGlobe,
                onOpen: () => openBrowser(sessionId),
              },
            ].map(({ label, icon: Icon, onOpen }) => (
              <SelectCard
                key={label}
                role="button"
                tabIndex={0}
                aria-label={label}
                state="filled"
                border="none"
                padding={3}
                rounding={3}
                onClick={onOpen}
              >
                <div className="flex items-center gap-3">
                  <Icon size={20} className="stroke-text-03" aria-hidden />
                  <Text font="main-ui-muted">{label}</Text>
                </div>
              </SelectCard>
            ))}
          </WorkspaceHome>
        )}
        {mountedResources.map((resource) => {
          const tab = resource.tab;
          const id = panelTabId(tab);
          const visible = isOpen && id === activeId;
          return (
            <div
              key={`${id}:${resource.mountKey}`}
              id={resourcePanelDomId(id)}
              role={tabs.includes(tab) ? "tabpanel" : undefined}
              aria-labelledby={
                tabs.includes(tab) ? resourceTabDomId(id) : undefined
              }
              aria-hidden={!visible}
              inert={!visible}
              className={cn(
                "absolute inset-0",
                !visible && "invisible pointer-events-none"
              )}
            >
              {tab.kind === "outputs" ? (
                <OutputsTab
                  sessionId={contentSessionId}
                  searchQuery={outputsSearch}
                  isActive={visible && runtimeReady}
                  onFileOpen={(path, name) =>
                    useBuildSessionStore
                      .getState()
                      .openFilePreview(sessionId, path, name)
                  }
                />
              ) : tab.kind === "files" ? (
                <FilesTab
                  sessionId={contentSessionId}
                  searchQuery={search}
                  onFileClick={
                    contentSessionId
                      ? (path, fileName) =>
                          useBuildSessionStore
                            .getState()
                            .openFilePreview(sessionId, path, fileName)
                      : undefined
                  }
                  refreshKey={resource.refreshKey}
                  onRefreshingChange={(pending) =>
                    onResourceLoading(tab, pending)
                  }
                  isProvisioning={!sessionId && isProvisioning}
                  isActive={visible && runtimeReady}
                  canLoad={runtimeReady}
                />
              ) : tab.kind === "file" && contentSessionId ? (
                <RestoredFileResource
                  tab={tab}
                  sessionId={contentSessionId}
                  filePath={tab.path}
                  revision={session?.outputInventory?.[tab.path]?.revision}
                  refreshKey={
                    (session?.filePreviewRefreshKeys[tab.path] ?? 0) +
                    resource.refreshKey +
                    (session?.webappNeedsRemount ?? 0)
                  }
                  isActive={visible && runtimeReady}
                  viewState={resource}
                  onViewStateChange={updateResource}
                  onLoading={onResourceLoading}
                />
              ) : tab.kind === "browser" ? (
                <BrowserTab
                  resourceId={id}
                  onLoadingChange={(_, pending) =>
                    onResourceLoading(tab, pending)
                  }
                  accessRevoked={accessRevoked}
                  apps={apps}
                  appId={tab.appId}
                  discoveryState={discoveryState}
                  refreshKey={
                    resource.refreshKey + (session?.webappNeedsRemount ?? 0)
                  }
                  onNavigate={(appId) =>
                    navigateBrowser(
                      sessionId,
                      id,
                      appId,
                      apps.find((app) => app.id === appId)?.name
                    )
                  }
                />
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}

interface RestoredFileResourceProps {
  tab: PanelTab;
  sessionId: string;
  filePath: string;
  revision?: string;
  refreshKey: number;
  isActive: boolean;
  viewState: FileResourceViewState;
  onViewStateChange: (
    tab: PanelTab,
    update: Partial<FileResourceViewState>
  ) => void;
  onLoading: (tab: PanelTab, pending: boolean) => void;
}

function RestoredFileResourceView({
  tab,
  onLoading,
  viewState,
  onViewStateChange,
  ...preview
}: RestoredFileResourceProps) {
  const onRefreshingChange = useCallback(
    (pending: boolean) => onLoading(tab, pending),
    [onLoading, tab]
  );
  const onSlideChange = useCallback(
    (slide: number) => onViewStateChange(tab, { slide }),
    [onViewStateChange, tab]
  );
  const onScrollTopChange = useCallback(
    (scrollTop: number) => onViewStateChange(tab, { scrollTop }),
    [onViewStateChange, tab]
  );
  return (
    <FilePreviewContent
      {...preview}
      onRefreshingChange={onRefreshingChange}
      initialSlide={viewState.slide}
      onSlideChange={onSlideChange}
      initialScrollTop={viewState.scrollTop}
      onScrollTopChange={onScrollTopChange}
    />
  );
}

const RestoredFileResource = memo(RestoredFileResourceView);
