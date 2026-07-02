"use client";

import { memo, useState, useEffect, useCallback } from "react";
import useSWR from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  useSession,
  useWebappNeedsRefresh,
  useBuildSessionStore,
  usePanelTabs,
  useActiveOutputTab,
  useActivePanelTabId,
  usePreProvisionedSessionId,
  useIsPreProvisioning,
  useTabHistory,
  OutputTabType,
} from "@/app/craft/hooks/useBuildSessionStore";
import { type PanelTab, panelTabId } from "@/app/craft/types/displayTypes";
import {
  fetchWebappInfo,
  fetchArtifacts,
  exportDocx,
} from "@/app/craft/services/apiServices";
import { getFileIcon } from "@/lib/utils";
import { cn } from "@opal/utils";
import { Text } from "@opal/components";
import { SvgGlobe, SvgHardDrive, SvgFiles, SvgX } from "@opal/icons";
import { IconProps } from "@opal/types";
import CraftingLoader from "@/app/craft/components/CraftingLoader";

// Output panel sub-components. UrlBar is the always-visible chrome and stays
// static; the heavy tab bodies (preview iframe, file browser, artifact list,
// and the file preview → markdown/pdf/pptx viewers) are dynamically imported
// so they're split out of the first-load bundle and only fetched when the
// panel opens.
import dynamic from "next/dynamic";
import UrlBar from "@/app/craft/components/output-panel/UrlBar";

const PreviewTab = dynamic(
  () => import("@/app/craft/components/output-panel/PreviewTab"),
  { ssr: false }
);
const FilesTab = dynamic(
  () => import("@/app/craft/components/output-panel/FilesTab"),
  { ssr: false }
);
const ArtifactsTab = dynamic(
  () => import("@/app/craft/components/output-panel/ArtifactsTab"),
  { ssr: false }
);
const FilePreviewContent = dynamic(
  () =>
    import("@/app/craft/components/output-panel/FilePreviewContent").then(
      (m) => m.FilePreviewContent
    ),
  { ssr: false }
);

type TabValue = OutputTabType;

const tabs: { value: TabValue; label: string; icon: React.FC<IconProps> }[] = [
  { value: "preview", label: "Preview", icon: SvgGlobe },
  { value: "files", label: "Files", icon: SvgHardDrive },
  { value: "artifacts", label: "Artifacts", icon: SvgFiles },
];

interface BuildOutputPanelProps {
  isOpen: boolean;
}

/**
 * BuildOutputPanel - Right panel showing preview, files, and artifacts
 *
 * Features:
 * - Tabbed interface (Preview, Files, Artifacts)
 * - Live preview iframe for webapp artifacts
 * - File browser for exploring sandbox filesystem
 * - Artifact list with download/view options
 */
const BuildOutputPanel = memo(({ isOpen }: BuildOutputPanelProps) => {
  const session = useSession();
  const preProvisionedSessionId = usePreProvisionedSessionId();
  const isPreProvisioning = useIsPreProvisioning();

  // Get active tab state from store
  const activeOutputTab = useActiveOutputTab();
  const activePanelTabId = useActivePanelTabId();
  const panelTabs = usePanelTabs();

  // Store actions
  const setActiveOutputTab = useBuildSessionStore(
    (state) => state.setActiveOutputTab
  );
  const setNoSessionActiveOutputTab = useBuildSessionStore(
    (state) => state.setNoSessionActiveOutputTab
  );
  const openFilePreview = useBuildSessionStore(
    (state) => state.openFilePreview
  );
  const closeFilePreview = useBuildSessionStore(
    (state) => state.closeFilePreview
  );
  const closePanelTab = useBuildSessionStore((state) => state.closePanelTab);
  const setActivePanelTabId = useBuildSessionStore(
    (state) => state.setActivePanelTabId
  );

  // Store actions for refresh
  const triggerFilesRefresh = useBuildSessionStore(
    (state) => state.triggerFilesRefresh
  );

  // Counters to force-reload previews
  const [previewRefreshKey, setPreviewRefreshKey] = useState(0);
  const [filePreviewRefreshKey, setFilePreviewRefreshKey] = useState(0);

  // Determine which tab is visually active
  const isFilePreviewActive = activePanelTabId !== null;
  const activeTab = isFilePreviewActive ? null : activeOutputTab;

  const handlePinnedTabClick = (tab: TabValue) => {
    if (session?.id) {
      setActiveOutputTab(session.id, tab);
    } else {
      // No session - use temporary state for tab switching
      setNoSessionActiveOutputTab(tab);
    }
  };

  const handlePanelTabClick = useCallback(
    (tabId: string) => {
      if (!session?.id) return;
      setActivePanelTabId(session.id, tabId);
    },
    [session?.id, setActivePanelTabId]
  );

  const handlePanelTabClose = useCallback(
    (e: React.MouseEvent, tab: PanelTab) => {
      e.stopPropagation();
      if (!session?.id) return;
      if (tab.kind === "file") {
        closeFilePreview(session.id, tab.path);
      } else {
        closePanelTab(session.id, panelTabId(tab));
      }
    },
    [session?.id, closeFilePreview, closePanelTab]
  );

  const handleFileClick = (path: string, fileName: string) => {
    if (session?.id) {
      openFilePreview(session.id, path, fileName);
    }
  };

  // Track when panel animation completes (defer fetch until fully open)
  const [isFullyOpen, setIsFullyOpen] = useState(false);
  // Track when content should unmount (delayed on close for animation)
  const [shouldRenderContent, setShouldRenderContent] = useState(false);

  useEffect(() => {
    if (isOpen) {
      // Render content immediately on open
      setShouldRenderContent(true);
      // Wait for 300ms CSS transition to complete before fetching
      const timer = setTimeout(() => setIsFullyOpen(true), 300);
      return () => clearTimeout(timer);
    } else {
      // Stop fetching immediately
      setIsFullyOpen(false);
      // Delay unmount until close animation completes
      const timer = setTimeout(() => setShouldRenderContent(false), 300);
      return () => clearTimeout(timer);
    }
  }, [isOpen]);

  // Session-scoped URL caching
  const [cachedWebappUrl, setCachedWebappUrl] = useState<string | null>(null);
  const [cachedForSessionId, setCachedForSessionId] = useState<string | null>(
    null
  );

  // Clear cache when session changes
  useEffect(() => {
    if (session?.id !== cachedForSessionId) {
      setCachedWebappUrl(null);
      setCachedForSessionId(session?.id ?? null);
    }
  }, [session?.id, cachedForSessionId]);

  // Webapp refresh trigger from streaming / restore
  const webappNeedsRefresh = useWebappNeedsRefresh();

  // Track polling window: poll for up to 30s after a restore/refresh trigger
  const [pollingDeadline, setPollingDeadline] = useState<number | null>(null);
  const [isWebappReady, setIsWebappReady] = useState(false);

  // When webappNeedsRefresh bumps (restore or file edit), start a 30s polling window
  // and reset readiness so we poll until the server is back up
  useEffect(() => {
    if (webappNeedsRefresh > 0) {
      setPollingDeadline(Date.now() + 30_000);
      setIsWebappReady(false);

      // Force a re-render after 30s to stop polling even if server never responded
      const timer = setTimeout(() => setPollingDeadline(null), 30_000);
      return () => clearTimeout(timer);
    }
  }, [webappNeedsRefresh]);

  // Fetch webapp info from dedicated endpoint
  // Only fetch for real sessions when panel is fully open
  const shouldFetchWebapp =
    isFullyOpen &&
    session?.id &&
    !session.id.startsWith("temp-") &&
    session.status !== "creating";

  // Poll every 2s while NextJS is starting up (capped at 30s), then stop
  const shouldPoll =
    !isWebappReady && pollingDeadline !== null && Date.now() < pollingDeadline;

  const { data: webappInfo, mutate } = useSWR(
    shouldFetchWebapp ? SWR_KEYS.buildSessionWebappInfo(session.id) : null,
    () => (session?.id ? fetchWebappInfo(session.id) : null),
    {
      refreshInterval: shouldPoll ? 2000 : 0,
      revalidateOnFocus: true,
      keepPreviousData: true,
    }
  );

  // Update readiness from SWR response and clear polling deadline
  useEffect(() => {
    if (webappInfo?.ready) {
      setIsWebappReady(true);
      setPollingDeadline(null);
    }
  }, [webappInfo?.ready]);

  // Update cache when SWR returns data for current session
  useEffect(() => {
    if (webappInfo?.webapp_url && session?.id === cachedForSessionId) {
      setCachedWebappUrl(webappInfo.webapp_url);
    }
  }, [webappInfo?.webapp_url, session?.id, cachedForSessionId]);

  // Refresh when web/ file changes or after restore.
  // webappNeedsRefresh is a counter that increments on each edit/restore,
  // ensuring each triggers a new refresh even if the panel is already open.
  // Also bump previewRefreshKey so the iframe actually remounts — SWR
  // re-fetching webapp-info isn't enough when the URL stays the same.
  useEffect(() => {
    if (webappNeedsRefresh > 0 && isFullyOpen && session?.id) {
      mutate();
      setPreviewRefreshKey((k) => k + 1);
    }
  }, [webappNeedsRefresh, isFullyOpen, mutate, session?.id]);

  const webappUrl = webappInfo?.webapp_url ?? null;

  // Use cache only if it belongs to current session
  const validCachedUrl =
    cachedForSessionId === session?.id ? cachedWebappUrl : null;
  const displayUrl = webappUrl ?? validCachedUrl;

  // Tab navigation history
  const tabHistory = useTabHistory();
  const navigateTabBack = useBuildSessionStore(
    (state) => state.navigateTabBack
  );
  const navigateTabForward = useBuildSessionStore(
    (state) => state.navigateTabForward
  );

  const canGoBack = tabHistory.currentIndex > 0;
  const canGoForward = tabHistory.currentIndex < tabHistory.entries.length - 1;

  const handleBack = useCallback(() => {
    if (session?.id) {
      navigateTabBack(session.id);
    }
  }, [session?.id, navigateTabBack]);

  const handleForward = useCallback(() => {
    if (session?.id) {
      navigateTabForward(session.id);
    }
  }, [session?.id, navigateTabForward]);

  // Resolve the active transient tab object (if any)
  const activePanel: PanelTab | undefined = panelTabs.find(
    (t) => panelTabId(t) === activePanelTabId
  );
  const activeFilePath = activePanel?.kind === "file" ? activePanel.path : null;

  // Determine if the active file preview is a markdown or pptx file (for download buttons)
  const isMarkdownPreview =
    isFilePreviewActive && activeFilePath && /\.md$/i.test(activeFilePath);

  const isPptxPreview =
    isFilePreviewActive && activeFilePath && /\.pptx$/i.test(activeFilePath);

  const isPdfPreview =
    isFilePreviewActive && activeFilePath && /\.pdf$/i.test(activeFilePath);

  const [isExportingDocx, setIsExportingDocx] = useState(false);

  const handleDocxDownload = useCallback(async () => {
    if (!session?.id || !activeFilePath) return;
    setIsExportingDocx(true);
    try {
      const blob = await exportDocx(session.id, activeFilePath);
      const fileName = activeFilePath.split("/").pop() || activeFilePath;
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = fileName.replace(/\.md$/i, ".docx");
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error("Failed to export as DOCX:", err);
    } finally {
      setIsExportingDocx(false);
    }
  }, [session?.id, activeFilePath]);

  const handleRawFileDownload = useCallback(() => {
    if (!session?.id || !activeFilePath) return;
    const encodedPath = activeFilePath
      .split("/")
      .map((s) => encodeURIComponent(s))
      .join("/");
    const link = document.createElement("a");
    link.href = `/api/build/sessions/${session.id}/artifacts/${encodedPath}`;
    link.download = activeFilePath.split("/").pop() || activeFilePath;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }, [session?.id, activeFilePath]);

  // Unified refresh handler — dispatches based on the active tab/preview
  const handleRefresh = useCallback(() => {
    if (isFilePreviewActive) {
      // Transient panel tab: bump key to reload standalone + content previews
      setFilePreviewRefreshKey((k) => k + 1);
    } else if (activeOutputTab === "preview") {
      // Web preview tab: remount the iframe
      setPreviewRefreshKey((k) => k + 1);
    } else if (activeOutputTab === "files" && session?.id) {
      // Files tab: clear cache and re-fetch directory listing
      triggerFilesRefresh(session.id);
    }
  }, [isFilePreviewActive, activeOutputTab, session?.id, triggerFilesRefresh]);

  // Fetch artifacts - poll every 5 seconds when on artifacts tab
  const shouldFetchArtifacts =
    session?.id &&
    !session.id.startsWith("temp-") &&
    session.status !== "creating" &&
    activeTab === "artifacts";

  const { data: polledArtifacts } = useSWR(
    shouldFetchArtifacts ? SWR_KEYS.buildSessionArtifacts(session.id) : null,
    () => (session?.id ? fetchArtifacts(session.id) : null),
    {
      refreshInterval: 5000, // Refresh every 5 seconds to catch new artifacts
      revalidateOnFocus: true,
    }
  );

  // Use polled artifacts if available, otherwise fall back to session store
  const artifacts = polledArtifacts ?? session?.artifacts ?? [];

  return (
    <div
      className={cn(
        "absolute z-20 inset-y-0 right-0 w-1/2 flex flex-col border-l border-border-01 bg-background-neutral-00 overflow-hidden transition-transform duration-300 ease-in-out",
        isOpen ? "translate-x-0" : "translate-x-full pointer-events-none"
      )}
    >
      {/* Tab List - Chrome-style tabs */}
      <div className="flex flex-col w-full">
        {/* Tabs row */}
        <div className="flex items-end w-full pt-1 bg-background-tint-03">
          {/* Scrollable tabs container */}
          <div className="flex items-end flex-1 pl-2 pr-2 overflow-x-auto [&::-webkit-scrollbar]:hidden [-ms-overflow-style:none] [scrollbar-width:none]">
            {/* Pinned tabs */}
            {tabs.map((tab) => {
              const Icon = tab.icon;
              const isActive = activeTab === tab.value;
              // Disable artifacts tab when no session
              const isDisabled = tab.value === "artifacts" && !session;
              return (
                <button
                  key={tab.value}
                  onClick={() => !isDisabled && handlePinnedTabClick(tab.value)}
                  disabled={isDisabled}
                  title={
                    isDisabled
                      ? "Start building something to see artifacts!"
                      : undefined
                  }
                  className={cn(
                    "relative inline-flex items-center justify-center gap-2 px-5 py-1.5 rounded-t-lg",
                    "max-w-[15%] min-w-fit",
                    isDisabled
                      ? "text-text-02 bg-transparent cursor-not-allowed"
                      : isActive
                        ? "bg-background-neutral-00 text-text-04 z-10"
                        : "text-text-03 bg-transparent hover:bg-background-tint-02"
                  )}
                >
                  {/* Left curved joint — bleeds active tab into the row */}
                  {isActive && (
                    <div
                      className="absolute -left-2 bottom-0 w-2 h-2 bg-background-neutral-00 pointer-events-none"
                      style={{
                        maskImage:
                          "radial-gradient(circle at 0 0, transparent 8px, black 8px)",
                        WebkitMaskImage:
                          "radial-gradient(circle at 0 0, transparent 8px, black 8px)",
                      }}
                    />
                  )}
                  <Icon
                    size={16}
                    className={cn(
                      "stroke-current shrink-0",
                      isDisabled
                        ? "stroke-text-02"
                        : isActive
                          ? "stroke-text-04"
                          : "stroke-text-03"
                    )}
                  />
                  <Text color={isDisabled ? "text-02" : "text-05"} maxLines={1}>
                    {tab.label}
                  </Text>
                  {/* Right curved joint */}
                  {isActive && (
                    <div
                      className="absolute -right-2 bottom-0 w-2 h-2 bg-background-neutral-00 pointer-events-none"
                      style={{
                        maskImage:
                          "radial-gradient(circle at 100% 0, transparent 8px, black 8px)",
                        WebkitMaskImage:
                          "radial-gradient(circle at 100% 0, transparent 8px, black 8px)",
                      }}
                    />
                  )}
                </button>
              );
            })}

            {/* Separator between pinned and transient tabs */}
            {panelTabs.length > 0 && (
              <div className="w-px h-5 bg-border-02 mx-2 mb-1 self-center" />
            )}

            {/* Transient panel tabs */}
            {panelTabs.map((tab) => {
              const id = panelTabId(tab);
              const isActive = activePanelTabId === id;

              switch (tab.kind) {
                case "file": {
                  const TabIcon = getFileIcon(tab.fileName);
                  return (
                    <button
                      key={id}
                      onClick={() => handlePanelTabClick(id)}
                      className={cn(
                        "group relative inline-flex items-center justify-center gap-1.5 px-3 pr-2 py-1.5 rounded-t-lg",
                        "max-w-[150px] min-w-fit",
                        isActive
                          ? "bg-background-neutral-00 text-text-04 z-10"
                          : "text-text-03 bg-transparent hover:bg-background-tint-02"
                      )}
                    >
                      {isActive && (
                        <div
                          className="absolute -left-2 bottom-0 w-2 h-2 bg-background-neutral-00 pointer-events-none"
                          style={{
                            maskImage:
                              "radial-gradient(circle at 0 0, transparent 8px, black 8px)",
                            WebkitMaskImage:
                              "radial-gradient(circle at 0 0, transparent 8px, black 8px)",
                          }}
                        />
                      )}
                      <TabIcon
                        size={14}
                        className={cn(
                          "stroke-current shrink-0",
                          isActive ? "stroke-text-04" : "stroke-text-03"
                        )}
                      />
                      <Text font="secondary-body" color="text-05" maxLines={1}>
                        {tab.fileName}
                      </Text>
                      {/* Close button */}
                      <button
                        onClick={(e) => handlePanelTabClose(e, tab)}
                        className={cn(
                          "shrink-0 p-0.5 rounded-sm hover:bg-background-tint-03 transition-colors",
                          isActive
                            ? "opacity-100"
                            : "opacity-0 group-hover:opacity-100"
                        )}
                        aria-label={`Close ${tab.fileName}`}
                      >
                        <SvgX size={12} className="stroke-text-03" />
                      </button>
                      {isActive && (
                        <div
                          className="absolute -right-2 bottom-0 w-2 h-2 bg-background-neutral-00 pointer-events-none"
                          style={{
                            maskImage:
                              "radial-gradient(circle at 100% 0, transparent 8px, black 8px)",
                            WebkitMaskImage:
                              "radial-gradient(circle at 100% 0, transparent 8px, black 8px)",
                          }}
                        />
                      )}
                    </button>
                  );
                }
              }
            })}
          </div>
        </div>
        {/* White bar connecting tabs to content */}
        <div className="h-2 w-full bg-background-neutral-00" />
      </div>

      {/* URL Bar - Chrome-style */}
      <UrlBar
        displayUrl={
          isFilePreviewActive && activeFilePath
            ? `sandbox://${activeFilePath}`
            : activeOutputTab === "preview"
              ? session
                ? displayUrl || "Loading..."
                : "no-active-sandbox://"
              : activeOutputTab === "files"
                ? session
                  ? "sandbox://"
                  : preProvisionedSessionId
                    ? "pre-provisioned-sandbox://"
                    : isPreProvisioning
                      ? "provisioning-sandbox://..."
                      : "no-sandbox://"
                : "artifacts://"
        }
        showNavigation={true}
        canGoBack={canGoBack}
        canGoForward={canGoForward}
        onBack={handleBack}
        onForward={handleForward}
        previewUrl={
          !isFilePreviewActive &&
          activeOutputTab === "preview" &&
          displayUrl &&
          displayUrl.startsWith("http")
            ? displayUrl
            : null
        }
        onDownloadRaw={
          isMarkdownPreview || isPptxPreview || isPdfPreview
            ? handleRawFileDownload
            : undefined
        }
        downloadRawTooltip={
          isPdfPreview
            ? "Download PDF"
            : isPptxPreview
              ? "Download PPTX"
              : "Download MD file"
        }
        onDownload={isMarkdownPreview ? handleDocxDownload : undefined}
        isDownloading={isExportingDocx}
        onRefresh={handleRefresh}
        sessionId={
          !isFilePreviewActive &&
          activeOutputTab === "preview" &&
          session?.id &&
          displayUrl?.startsWith("http")
            ? session.id
            : undefined
        }
        sharingScope={webappInfo?.sharing_scope ?? "private"}
        onScopeChange={mutate}
      />

      {/* Tab Content */}
      <div className="flex-1 overflow-hidden rounded-b-08">
        {/* Transient panel tab content - shown when a panel tab is active */}
        {isFilePreviewActive && activePanel?.kind === "file" && session?.id && (
          <FilePreviewContent
            sessionId={session.id}
            filePath={activePanel.path}
            refreshKey={filePreviewRefreshKey}
          />
        )}
        {/* Pinned tab content - only show when no file preview is active */}
        {!isFilePreviewActive && (
          <>
            {activeOutputTab === "preview" &&
              shouldRenderContent &&
              // Show crafting loader only when no session exists (welcome state)
              // Otherwise, PreviewTab handles the loading/iframe display
              (!session ? (
                <CraftingLoader />
              ) : (
                <PreviewTab
                  webappUrl={displayUrl}
                  refreshKey={previewRefreshKey}
                />
              ))}
            {activeOutputTab === "files" && (
              <FilesTab
                sessionId={session?.id ?? preProvisionedSessionId}
                onFileClick={session ? handleFileClick : undefined}
                isPreProvisioned={!session && !!preProvisionedSessionId}
                isProvisioning={!session && isPreProvisioning}
              />
            )}
            {activeOutputTab === "artifacts" && (
              <ArtifactsTab
                artifacts={artifacts}
                sessionId={session?.id ?? null}
              />
            )}
          </>
        )}
      </div>
    </div>
  );
});
BuildOutputPanel.displayName = "BuildOutputPanel";
export default BuildOutputPanel;
