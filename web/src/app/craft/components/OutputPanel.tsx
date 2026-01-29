"use client";

import { memo, useState, useEffect, useCallback } from "react";
import useSWR from "swr";
import {
  useSession,
  useWebappNeedsRefresh,
  useBuildSessionStore,
  useFilePreviewTabs,
  useActiveOutputTab,
  useActiveFilePreviewPath,
  usePreProvisionedSessionId,
  useIsPreProvisioning,
  useTabHistory,
  OutputTabType,
} from "@/app/craft/hooks/useBuildSessionStore";
import {
  fetchWebappInfo,
  fetchArtifacts,
  exportDocx,
} from "@/app/craft/services/apiServices";
import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import {
  SvgGlobe,
  SvgHardDrive,
  SvgFiles,
  SvgFileText,
  SvgX,
  SvgMinus,
  SvgMaximize2,
} from "@opal/icons";
import { IconProps } from "@opal/types";
import CraftingLoader from "@/app/craft/components/CraftingLoader";

// Output panel sub-components
import UrlBar from "@/app/craft/components/output-panel/UrlBar";
import PreviewTab from "@/app/craft/components/output-panel/PreviewTab";
import { FilePreviewContent } from "@/app/craft/components/output-panel/FilePreviewContent";
import FilesTab from "@/app/craft/components/output-panel/FilesTab";
import ArtifactsTab from "@/app/craft/components/output-panel/ArtifactsTab";

type TabValue = OutputTabType;

const tabs: { value: TabValue; label: string; icon: React.FC<IconProps> }[] = [
  { value: "preview", label: "Preview", icon: SvgGlobe },
  { value: "files", label: "Files", icon: SvgHardDrive },
  { value: "artifacts", label: "Artifacts", icon: SvgFiles },
];

interface BuildOutputPanelProps {
  onClose: () => void;
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
const BuildOutputPanel = memo(({ onClose, isOpen }: BuildOutputPanelProps) => {
  const session = useSession();
  const preProvisionedSessionId = usePreProvisionedSessionId();
  const isPreProvisioning = useIsPreProvisioning();

  // Get active tab state from store
  const activeOutputTab = useActiveOutputTab();
  const activeFilePreviewPath = useActiveFilePreviewPath();
  const filePreviewTabs = useFilePreviewTabs();

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
  const setActiveFilePreviewPath = useBuildSessionStore(
    (state) => state.setActiveFilePreviewPath
  );

  // Determine which tab is visually active
  const isFilePreviewActive = activeFilePreviewPath !== null;
  const activeTab = isFilePreviewActive ? null : activeOutputTab;

  const handlePinnedTabClick = (tab: TabValue) => {
    if (session?.id) {
      setActiveOutputTab(session.id, tab);
    } else {
      // No session - use temporary state for tab switching
      setNoSessionActiveOutputTab(tab);
    }
  };

  const handlePreviewTabClick = (path: string) => {
    if (session?.id) {
      setActiveFilePreviewPath(session.id, path);
    }
  };

  const handlePreviewTabClose = (e: React.MouseEvent, path: string) => {
    e.stopPropagation(); // Don't trigger tab click
    if (session?.id) {
      closeFilePreview(session.id, path);
    }
  };

  const handleFileClick = (path: string, fileName: string) => {
    if (session?.id) {
      openFilePreview(session.id, path, fileName);
    }
  };

  const handleMaximize = () => {
    setIsMaximized((prev) => !prev);
  };

  // Track when panel animation completes (defer fetch until fully open)
  const [isFullyOpen, setIsFullyOpen] = useState(false);
  // Track when content should unmount (delayed on close for animation)
  const [shouldRenderContent, setShouldRenderContent] = useState(false);
  // Track if panel is maximized
  const [isMaximized, setIsMaximized] = useState(false);

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

  // Webapp refresh trigger from streaming
  const webappNeedsRefresh = useWebappNeedsRefresh();

  // Fetch webapp info from dedicated endpoint
  // Only fetch for real sessions when panel is fully open
  const shouldFetchWebapp =
    isFullyOpen &&
    session?.id &&
    !session.id.startsWith("temp-") &&
    session.status !== "creating";

  const { data: webappInfo, mutate } = useSWR(
    shouldFetchWebapp ? `/api/build/sessions/${session.id}/webapp-info` : null,
    () => (session?.id ? fetchWebappInfo(session.id) : null),
    {
      refreshInterval: 0, // Disable polling, use event-based refresh
      revalidateOnFocus: true,
      keepPreviousData: true, // Stale-while-revalidate
    }
  );

  // Update cache when SWR returns data for current session
  useEffect(() => {
    if (webappInfo?.webapp_url && session?.id === cachedForSessionId) {
      setCachedWebappUrl(webappInfo.webapp_url);
    }
  }, [webappInfo?.webapp_url, session?.id, cachedForSessionId]);

  // Refresh when web/ file changes
  // webappNeedsRefresh is a counter that increments on each edit, ensuring
  // each edit triggers a new refresh even if the panel is already open
  useEffect(() => {
    if (webappNeedsRefresh > 0 && isFullyOpen && session?.id) {
      mutate();
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

  // Determine if the active file preview is a markdown file (for download button)
  const isMarkdownPreview =
    isFilePreviewActive &&
    activeFilePreviewPath &&
    /\.md$/i.test(activeFilePreviewPath);

  const [isExportingDocx, setIsExportingDocx] = useState(false);

  const handleDocxDownload = useCallback(async () => {
    if (!session?.id || !activeFilePreviewPath) return;
    setIsExportingDocx(true);
    try {
      const blob = await exportDocx(session.id, activeFilePreviewPath);
      const fileName =
        activeFilePreviewPath.split("/").pop() || activeFilePreviewPath;
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
  }, [session?.id, activeFilePreviewPath]);

  const handleMdDownload = useCallback(() => {
    if (!session?.id || !activeFilePreviewPath) return;
    const encodedPath = activeFilePreviewPath
      .split("/")
      .map((s) => encodeURIComponent(s))
      .join("/");
    const link = document.createElement("a");
    link.href = `/api/build/sessions/${session.id}/artifacts/${encodedPath}`;
    link.download =
      activeFilePreviewPath.split("/").pop() || activeFilePreviewPath;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }, [session?.id, activeFilePreviewPath]);

  // Fetch artifacts - poll every 5 seconds when on artifacts tab
  const shouldFetchArtifacts =
    session?.id &&
    !session.id.startsWith("temp-") &&
    session.status !== "creating" &&
    activeTab === "artifacts";

  const { data: polledArtifacts } = useSWR(
    shouldFetchArtifacts ? `/api/build/sessions/${session.id}/artifacts` : null,
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
        "absolute z-20 flex flex-col border rounded-12 border-border-01 bg-background-neutral-00 overflow-hidden transition-all duration-300 ease-in-out",
        isMaximized
          ? "top-4 right-16 bottom-4 w-[calc(100%-8rem)]"
          : "top-4 right-4 bottom-4 w-[calc(50%-2rem)]",
        isOpen
          ? "opacity-100 translate-x-0"
          : "opacity-0 translate-x-full pointer-events-none"
      )}
      style={{
        boxShadow: "0 8px 60px 30px rgba(0, 0, 0, 0.07)",
      }}
    >
      {/* Tab List - Chrome-style tabs */}
      <div className="flex flex-col w-full">
        {/* Tabs row */}
        <div className="flex items-end w-full pt-1.5 bg-background-tint-03">
          {/* macOS-style window controls - sticky on left */}
          <div className="group flex items-center gap-2.5 pl-4 pr-2 py-3 flex-shrink-0">
            <button
              onClick={onClose}
              className="relative w-3.5 h-3.5 rounded-full bg-[#ff5f57] hover:bg-[#ff3b30] transition-colors flex-shrink-0 flex items-center justify-center"
              aria-label="No action"
            >
              <SvgX
                size={12}
                strokeWidth={4}
                className="opacity-0 group-hover:opacity-100 transition-opacity"
                style={{ stroke: "#8a2e2a" }}
              />
            </button>
            <button
              onClick={onClose}
              className="relative w-3.5 h-3.5 rounded-full bg-[#ffbd2e] hover:bg-[#ffa000] transition-colors flex-shrink-0 flex items-center justify-center"
              aria-label="Close panel"
            >
              <SvgMinus
                size={12}
                strokeWidth={3}
                className="opacity-0 group-hover:opacity-100 transition-opacity"
                style={{ stroke: "#8a6618" }}
              />
            </button>
            <button
              onClick={handleMaximize}
              className="relative w-3.5 h-3.5 rounded-full bg-[#28ca42] hover:bg-[#1fb832] transition-colors flex-shrink-0 flex items-center justify-center"
              aria-label="Maximize panel"
            >
              <SvgMaximize2
                size={8}
                strokeWidth={2.5}
                className="opacity-0 group-hover:opacity-90 rotate-90 transition-opacity"
                style={{ stroke: "#155c24" }}
              />
            </button>
          </div>
          {/* Scrollable tabs container */}
          <div className="flex items-end gap-1.5 flex-1 pl-3 pr-2 overflow-x-auto [&::-webkit-scrollbar]:hidden [-ms-overflow-style:none] [scrollbar-width:none]">
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
                    "relative inline-flex items-center justify-center gap-2 px-5",
                    "max-w-[15%] min-w-fit",
                    isDisabled
                      ? "text-text-02 bg-transparent cursor-not-allowed py-1 mb-1"
                      : isActive
                        ? "bg-background-neutral-00 text-text-04 rounded-t-lg py-2"
                        : "text-text-03 bg-transparent hover:bg-background-tint-02 rounded-full py-1 mb-1"
                  )}
                >
                  {/* Left curved joint */}
                  {isActive && (
                    <div
                      className="absolute -left-3 bottom-0 w-3 h-3 bg-background-neutral-00"
                      style={{
                        maskImage:
                          "radial-gradient(circle at 0 0, transparent 12px, black 12px)",
                        WebkitMaskImage:
                          "radial-gradient(circle at 0 0, transparent 12px, black 12px)",
                      }}
                    />
                  )}
                  <Icon
                    size={16}
                    className={cn(
                      "stroke-current flex-shrink-0",
                      isDisabled
                        ? "stroke-text-02"
                        : isActive
                          ? "stroke-text-04"
                          : "stroke-text-03"
                    )}
                  />
                  <Text
                    className={cn("truncate", isDisabled && "text-text-02")}
                  >
                    {tab.label}
                  </Text>
                  {/* Right curved joint */}
                  {isActive && (
                    <div
                      className="absolute -right-3 bottom-0 w-3 h-3 bg-background-neutral-00"
                      style={{
                        maskImage:
                          "radial-gradient(circle at 100% 0, transparent 12px, black 12px)",
                        WebkitMaskImage:
                          "radial-gradient(circle at 100% 0, transparent 12px, black 12px)",
                      }}
                    />
                  )}
                </button>
              );
            })}

            {/* Separator between pinned and preview tabs */}
            {filePreviewTabs.length > 0 && (
              <div className="w-px h-5 bg-border-02 mx-2 mb-1 self-center" />
            )}

            {/* Preview tabs */}
            {filePreviewTabs.map((previewTab) => {
              const isActive = activeFilePreviewPath === previewTab.path;
              return (
                <button
                  key={previewTab.path}
                  onClick={() => handlePreviewTabClick(previewTab.path)}
                  className={cn(
                    "group relative inline-flex items-center justify-center gap-1.5 px-3 pr-2",
                    "max-w-[150px] min-w-fit",
                    isActive
                      ? "bg-background-neutral-00 text-text-04 rounded-t-lg py-2"
                      : "text-text-03 bg-transparent hover:bg-background-tint-02 rounded-full py-1 mb-1"
                  )}
                >
                  {/* Left curved joint */}
                  {isActive && (
                    <div
                      className="absolute -left-3 bottom-0 w-3 h-3 bg-background-neutral-00"
                      style={{
                        maskImage:
                          "radial-gradient(circle at 0 0, transparent 12px, black 12px)",
                        WebkitMaskImage:
                          "radial-gradient(circle at 0 0, transparent 12px, black 12px)",
                      }}
                    />
                  )}
                  <SvgFileText
                    size={14}
                    className={cn(
                      "stroke-current flex-shrink-0",
                      isActive ? "stroke-text-04" : "stroke-text-03"
                    )}
                  />
                  <Text className="truncate text-sm">
                    {previewTab.fileName}
                  </Text>
                  {/* Close button */}
                  <button
                    onClick={(e) => handlePreviewTabClose(e, previewTab.path)}
                    className={cn(
                      "flex-shrink-0 p-0.5 rounded hover:bg-background-tint-03 transition-colors",
                      isActive
                        ? "opacity-100"
                        : "opacity-0 group-hover:opacity-100"
                    )}
                    aria-label={`Close ${previewTab.fileName}`}
                  >
                    <SvgX size={12} className="stroke-text-03" />
                  </button>
                  {/* Right curved joint */}
                  {isActive && (
                    <div
                      className="absolute -right-3 bottom-0 w-3 h-3 bg-background-neutral-00"
                      style={{
                        maskImage:
                          "radial-gradient(circle at 100% 0, transparent 12px, black 12px)",
                        WebkitMaskImage:
                          "radial-gradient(circle at 100% 0, transparent 12px, black 12px)",
                      }}
                    />
                  )}
                </button>
              );
            })}
          </div>
        </div>
        {/* White bar connecting tabs to content */}
        <div className="h-2 w-full bg-background-neutral-00" />
      </div>

      {/* URL Bar - Chrome-style */}
      <UrlBar
        displayUrl={
          isFilePreviewActive && activeFilePreviewPath
            ? `sandbox://${activeFilePreviewPath}`
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
        onDownloadRaw={isMarkdownPreview ? handleMdDownload : undefined}
        onDownload={isMarkdownPreview ? handleDocxDownload : undefined}
        isDownloading={isExportingDocx}
      />

      {/* Tab Content */}
      <div className="flex-1 overflow-hidden rounded-b-08">
        {/* File preview content - shown when a preview tab is active */}
        {isFilePreviewActive && activeFilePreviewPath && session?.id && (
          <FilePreviewContent
            sessionId={session.id}
            filePath={activeFilePreviewPath}
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
                <PreviewTab webappUrl={displayUrl} />
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
