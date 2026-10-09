"use client";

import { useTranslations } from "next-intl";
import { memo, useState, useEffect, useCallback, useRef } from "react";
import useSWR from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  useSession,
  useWebappNeedsRefresh,
  useWebappNeedsRemount,
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
  downloadArtifactFile,
} from "@/app/craft/services/apiServices";
import { getFileIcon } from "@/lib/utils";
import { cn } from "@opal/utils";
import { useDirection } from "@radix-ui/react-direction";
import { Button, LineItemButton, Text, Tooltip } from "@opal/components";
import { SvgGlobe, SvgHardDrive, SvgFiles, SvgX, SvgLoader } from "@opal/icons";
import { IconProps } from "@opal/types";
import CraftingLoader from "@/app/craft/components/CraftingLoader";
import {
  getWebappState,
  type WebappState,
} from "@/app/craft/components/output-panel/types";

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

// The joint masks carve the corner nearest the tab, so the carved side
// follows the reading direction.
function jointMask(gradient: string): React.CSSProperties {
  return { maskImage: gradient, WebkitMaskImage: gradient };
}
function useJointMasks(): {
  start: React.CSSProperties;
  end: React.CSSProperties;
} {
  const rtl = useDirection() === "rtl";
  return {
    start: jointMask(
      `radial-gradient(circle at ${rtl ? "100%" : "0"} 0, transparent 8px, black 8px)`
    ),
    end: jointMask(
      `radial-gradient(circle at ${rtl ? "0" : "100%"} 0, transparent 8px, black 8px)`
    ),
  };
}

const BuildOutputPanel = memo(({ isOpen }: BuildOutputPanelProps) => {
  const t = useTranslations("craft.outputPanel");
  const jointMasks = useJointMasks();
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
  const [filesRefreshKey, setFilesRefreshKey] = useState(0);
  const [filesRefreshing, setFilesRefreshing] = useState(false);
  const handleFilesRefreshingChange = useCallback((loading: boolean) => {
    if (!loading) setFilesRefreshing(false);
  }, []);

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
    (tab: PanelTab) => {
      if (!session?.id) return;
      closePanelTab(session.id, panelTabId(tab));
    },
    [session?.id, closePanelTab]
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

  // Keep the last serving URL through a restart, but never across sessions.
  const [readyWebapp, setReadyWebapp] = useState<{
    sessionId: string;
    url: string;
  } | null>(null);

  // Webapp refresh trigger from streaming / restore
  const webappNeedsRefresh = useWebappNeedsRefresh();
  const webappNeedsRemount = useWebappNeedsRemount();

  // Track polling window: poll for up to 30s after a restore/refresh trigger
  const [pollingDeadline, setPollingDeadline] = useState<number | null>(null);

  // Refresh counters are session-local. Switching sessions must reset polling too.
  useEffect(() => {
    if (webappNeedsRefresh > 0) {
      setPollingDeadline(Date.now() + 30_000);

      // Force a re-render after 30s to stop polling even if server never responded
      const timer = setTimeout(() => setPollingDeadline(null), 30_000);
      return () => clearTimeout(timer);
    }
    setPollingDeadline(null);
  }, [session?.id, webappNeedsRefresh]);

  // Fetch webapp info from dedicated endpoint
  // Only fetch for real sessions when panel is fully open
  const canQueryWebapp = Boolean(
    session?.id &&
    !session.id.startsWith("temp-") &&
    session.status !== "creating"
  );
  const shouldFetchWebapp = isFullyOpen && canQueryWebapp;

  // Poll every 2s while NextJS is starting up (capped at 30s), then stop
  const shouldPoll = pollingDeadline !== null && Date.now() < pollingDeadline;

  const { data: webappInfo, mutate } = useSWR(
    shouldFetchWebapp && session
      ? SWR_KEYS.buildSessionWebappInfo(session.id)
      : null,
    () => (session?.id ? fetchWebappInfo(session.id) : null),
    {
      refreshInterval: shouldPoll ? 2000 : 0,
      revalidateOnFocus: true,
      // A successful read must stop each new polling window, even if readiness is unchanged.
      onSuccess: (data) => {
        if (data?.ready) setPollingDeadline(null);
      },
    }
  );

  // Gate on `ready`, not webapp_url alone - the URL can exist before the
  // dev server has actually started serving.
  useEffect(() => {
    setReadyWebapp((previous) => {
      if (session?.id && webappInfo?.ready && webappInfo.webapp_url) {
        return { sessionId: session.id, url: webappInfo.webapp_url };
      }
      return previous?.sessionId === session?.id ? previous : null;
    });
  }, [webappInfo?.ready, webappInfo?.webapp_url, session?.id]);

  // Re-fetch webapp-info when web/ files change or after restore. Live code
  // edits reach the iframe via the proxied HMR websocket — no remount needed.
  useEffect(() => {
    if (webappNeedsRefresh > 0 && isFullyOpen && session?.id) {
      mutate();
    }
  }, [webappNeedsRefresh, isFullyOpen, mutate, session?.id]);

  const iframeUrl =
    readyWebapp?.sessionId === session?.id ? (readyWebapp?.url ?? null) : null;

  const webappState: WebappState = getWebappState(
    iframeUrl !== null,
    webappInfo?.has_webapp
  );

  // Existing sessions stay on Preview while webapp-info loads. Provisioning
  // sessions cannot be queried yet, so they start on Files instead.
  const previewEnabled = canQueryWebapp && webappState !== "none";

  // Redirect away from the Preview tab while it's disabled without
  // mutating the user's stored tab preference.
  const effectiveActiveTab: TabValue | null =
    activeTab === "preview" && !previewEnabled ? "files" : activeTab;

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

  // Determine the active preview type for download actions.
  const isMarkdownPreview =
    isFilePreviewActive && activeFilePath && /\.md$/i.test(activeFilePath);

  const isPowerPointPreview =
    isFilePreviewActive && activeFilePath && /\.pptx?$/i.test(activeFilePath);

  const isPdfPreview =
    isFilePreviewActive && activeFilePath && /\.pdf$/i.test(activeFilePath);

  const contentSessionId: string | null =
    session?.id ?? preProvisionedSessionId;
  const selectedContentId: string | null = activePanel
    ? panelTabId(activePanel)
    : effectiveActiveTab;
  const [visitedTabs, setVisitedTabs] = useState<{
    sessionId: string | null;
    ids: string[];
  }>({ sessionId: contentSessionId, ids: [] });
  const availableContentIds: string[] = [
    ...tabs.map((tab) => tab.value),
    ...panelTabs.map(panelTabId),
  ];
  const retainedIds: string[] =
    visitedTabs.sessionId === contentSessionId
      ? visitedTabs.ids.filter(
          (id) => availableContentIds.includes(id) && id !== selectedContentId
        )
      : [];
  if (selectedContentId && shouldRenderContent)
    retainedIds.push(selectedContentId);
  const mountedIds: string[] = shouldRenderContent ? retainedIds.slice(-5) : [];
  if (
    visitedTabs.sessionId !== contentSessionId ||
    visitedTabs.ids.length !== mountedIds.length ||
    visitedTabs.ids.some((id, index) => id !== mountedIds[index])
  ) {
    setVisitedTabs({ sessionId: contentSessionId, ids: mountedIds });
  }

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
    downloadArtifactFile(session.id, activeFilePath);
  }, [session?.id, activeFilePath]);

  // Unified refresh handler — dispatches based on the active tab/preview
  const handleRefresh = useCallback(() => {
    if (isFilePreviewActive) {
      // Transient panel tab: bump key to reload standalone + content previews
      if (!session?.id || !activeFilePath) return;
      const store: ReturnType<typeof useBuildSessionStore.getState> =
        useBuildSessionStore.getState();
      const keys: Record<string, number> =
        store.sessions.get(session.id)?.filePreviewRefreshKeys ?? {};
      store.updateSessionData(session.id, {
        filePreviewRefreshKeys: {
          ...keys,
          [activeFilePath]: (keys[activeFilePath] ?? 0) + 1,
        },
      });
    } else if (effectiveActiveTab === "preview") {
      // Remount the iframe, and re-probe readiness — while the panel is
      // showing "none"/"starting" the iframe isn't mounted, so the key bump
      // alone would make refresh a no-op.
      setPreviewRefreshKey((k) => k + 1);
      mutate();
    } else if (effectiveActiveTab === "files" && contentSessionId) {
      // Files tab: revalidate the visible directory listings
      setFilesRefreshing(true);
      setFilesRefreshKey((key) => key + 1);
      triggerFilesRefresh(contentSessionId);
    } else if (effectiveActiveTab === "artifacts" && session?.id) {
      const store = useBuildSessionStore.getState();
      const current = store.sessions.get(session.id);
      void store.refreshOutputInventory(session.id, {
        silent: !current?.activeTurnId && current?.status !== "running",
      });
    }
  }, [
    isFilePreviewActive,
    activeFilePath,
    effectiveActiveTab,
    contentSessionId,
    session?.id,
    triggerFilesRefresh,
    mutate,
  ]);

  // Fetch artifacts - poll every 5 seconds when on artifacts tab
  const shouldFetchArtifacts =
    isOpen &&
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
      inert={!isOpen}
      className={cn(
        "absolute z-20 inset-y-0 end-0 w-1/2 flex flex-col border-s border-border-01 bg-background-neutral-00 overflow-hidden transition-transform duration-300 ease-in-out",
        // rtl: the panel hides toward the inline end, so RTL negates.
        isOpen
          ? "translate-x-0"
          : "translate-x-full rtl:-translate-x-full pointer-events-none"
      )}
    >
      {/* Tab List - Chrome-style tabs */}
      <div className="flex flex-col w-full">
        {/* Tabs row */}
        <div className="flex items-end w-full pt-1 bg-background-tint-03">
          {/* Scrollable tabs container */}
          <div className="flex items-end flex-1 ps-2 pe-2 overflow-x-auto [&::-webkit-scrollbar]:hidden [-ms-overflow-style:none] [scrollbar-width:none]">
            {/* Pinned tabs */}
            {tabs.map((tab) => {
              const Icon = tab.icon;
              const isActive = effectiveActiveTab === tab.value;
              const isDisabled =
                (tab.value === "artifacts" && !session) ||
                (tab.value === "preview" && !previewEnabled);
              const isStarting =
                tab.value === "preview" && webappState === "starting";
              const tooltip = isDisabled
                ? tab.value === "preview"
                  ? t("noWebapp.label")
                  : t("artifactsEmpty.tooltip")
                : isStarting
                  ? t("devServerStarting.tooltip")
                  : undefined;

              const tabButton = (
                <button
                  onClick={() => !isDisabled && handlePinnedTabClick(tab.value)}
                  aria-disabled={isDisabled}
                  aria-busy={isStarting}
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
                  {/* Start curved joint, bleeds the active tab into the row */}
                  {isActive && (
                    <div
                      className="absolute -start-2 bottom-0 w-2 h-2 bg-background-neutral-00 pointer-events-none"
                      style={jointMasks.start}
                    />
                  )}
                  {isStarting ? (
                    <SvgLoader
                      size={16}
                      className={cn(
                        "stroke-current shrink-0 motion-safe:animate-spin",
                        isActive ? "stroke-text-04" : "stroke-text-03"
                      )}
                    />
                  ) : (
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
                  )}
                  <Text color={isDisabled ? "text-02" : "text-05"} maxLines={1}>
                    {tab.label}
                  </Text>
                  {/* End curved joint */}
                  {isActive && (
                    <div
                      className="absolute -end-2 bottom-0 w-2 h-2 bg-background-neutral-00 pointer-events-none"
                      style={jointMasks.end}
                    />
                  )}
                </button>
              );

              return (
                <Tooltip key={tab.value} tooltip={tooltip} side="bottom">
                  {tabButton}
                </Tooltip>
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
                    <div
                      key={id}
                      className={cn(
                        "group relative inline-flex items-center justify-center pe-2 rounded-t-lg",
                        "max-w-[150px] min-w-0 shrink-0",
                        isActive
                          ? "bg-background-neutral-00 text-text-04 z-10"
                          : "text-text-03 bg-transparent hover:bg-background-tint-02"
                      )}
                    >
                      {isActive && (
                        <div
                          className="absolute -start-2 bottom-0 w-2 h-2 bg-background-neutral-00 pointer-events-none"
                          style={jointMasks.start}
                        />
                      )}
                      <div className="min-w-0 flex-1">
                        <LineItemButton
                          onClick={() => handlePanelTabClick(id)}
                          icon={TabIcon}
                          title={tab.fileName}
                          titleMaxLines={1}
                          sizePreset="secondary"
                          variant="heading"
                          padding={0}
                          rounding={2}
                          aria-pressed={isActive}
                        />
                      </div>
                      <div
                        className={cn(
                          "shrink-0 transition-opacity",
                          isActive
                            ? "opacity-100"
                            : "opacity-0 group-hover:opacity-100 no-hover:opacity-100"
                        )}
                      >
                        <Button
                          onClick={() => handlePanelTabClose(tab)}
                          icon={SvgX}
                          prominence="tertiary"
                          size="2xs"
                          aria-label={t("closeTab.ariaLabel", {
                            fileName: tab.fileName,
                          })}
                        />
                      </div>
                      {isActive && (
                        <div
                          className="absolute -end-2 bottom-0 w-2 h-2 bg-background-neutral-00 pointer-events-none"
                          style={jointMasks.end}
                        />
                      )}
                    </div>
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
            : effectiveActiveTab === "preview"
              ? session
                ? iframeUrl || "Loading..."
                : "no-active-sandbox://"
              : effectiveActiveTab === "files"
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
          effectiveActiveTab === "preview" &&
          iframeUrl &&
          iframeUrl.startsWith("http")
            ? iframeUrl
            : null
        }
        onDownloadRaw={
          isMarkdownPreview || isPowerPointPreview || isPdfPreview
            ? handleRawFileDownload
            : undefined
        }
        downloadRawTooltip={
          isPdfPreview
            ? "Download PDF"
            : isPowerPointPreview
              ? "Download PowerPoint"
              : "Download MD file"
        }
        onDownload={isMarkdownPreview ? handleDocxDownload : undefined}
        isDownloading={isExportingDocx}
        onRefresh={handleRefresh}
        isRefreshing={effectiveActiveTab === "files" && filesRefreshing}
        sessionId={
          !isFilePreviewActive &&
          effectiveActiveTab === "preview" &&
          session?.id &&
          iframeUrl?.startsWith("http")
            ? session.id
            : undefined
        }
        sharingScope={webappInfo?.sharing_scope ?? "private"}
        onScopeChange={mutate}
      />

      {/* Keep DOM order stable: moving an existing iframe can reload it. */}
      <div className="relative flex-1 overflow-hidden rounded-b-08">
        {[...mountedIds].sort().map((id) => {
          const isActive = isOpen && id === selectedContentId;
          const fileTab = panelTabs.find((tab) => panelTabId(tab) === id);
          return (
            <div
              key={`${contentSessionId}:${id}`}
              className={cn(
                "absolute inset-0",
                !isActive && "invisible pointer-events-none"
              )}
              aria-hidden={!isActive}
              inert={!isActive}
            >
              {fileTab && session ? (
                <FilePreviewContent
                  sessionId={session.id}
                  filePath={fileTab.path}
                  revision={session.outputInventory?.[fileTab.path]?.revision}
                  refreshKey={session.filePreviewRefreshKeys[fileTab.path] ?? 0}
                  isActive={isActive}
                />
              ) : id === "preview" ? (
                !session ? (
                  <CraftingLoader />
                ) : (
                  <PreviewTab
                    webappUrl={iframeUrl}
                    webappState={webappState}
                    refreshKey={previewRefreshKey + webappNeedsRemount}
                  />
                )
              ) : id === "files" ? (
                <FilesTab
                  sessionId={contentSessionId}
                  onFileClick={session ? handleFileClick : undefined}
                  onRefreshingChange={handleFilesRefreshingChange}
                  refreshKey={filesRefreshKey}
                  isPreProvisioned={!session && !!preProvisionedSessionId}
                  isProvisioning={!session && isPreProvisioning}
                  isActive={isActive}
                />
              ) : id === "artifacts" ? (
                <ArtifactsTab
                  artifacts={artifacts}
                  sessionId={session?.id ?? null}
                  isActive={isActive}
                />
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
});
BuildOutputPanel.displayName = "BuildOutputPanel";
export default BuildOutputPanel;
