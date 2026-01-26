"use client";

import { memo, useState, useEffect, useMemo, useRef, useCallback } from "react";
import useSWR from "swr";
import {
  useSession,
  useWebappNeedsRefresh,
  useBuildSessionStore,
  useFilePreviewTabs,
  useActiveOutputTab,
  useActiveFilePreviewPath,
  useFilesTabState,
  useTabHistory,
  usePreProvisionedSessionId,
  useIsPreProvisioning,
  Artifact,
  OutputTabType,
} from "@/app/build/hooks/useBuildSessionStore";
import {
  fetchWebappInfo,
  fetchDirectoryListing,
  fetchArtifacts,
  fetchFileContent,
} from "@/app/build/services/apiServices";
import { FileSystemEntry } from "@/app/build/types/streamingTypes";
import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import Button from "@/refresh-components/buttons/Button";
import {
  SvgGlobe,
  SvgHardDrive,
  SvgFiles,
  SvgFolder,
  SvgFolderOpen,
  SvgFileText,
  SvgChevronRight,
  SvgDownloadCloud,
  SvgX,
  SvgArrowLeft,
  SvgArrowRight,
  SvgImage,
  SvgExternalLink,
  SvgMinus,
  SvgMaximize2,
} from "@opal/icons";
import { Section } from "@/layouts/general-layouts";
import { IconProps } from "@opal/types";
import CraftingLoader from "@/app/build/components/CraftingLoader";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";

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
  const resetWebappRefresh = useBuildSessionStore(
    (state) => state.resetWebappRefresh
  );

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
  useEffect(() => {
    if (webappNeedsRefresh && isFullyOpen && session?.id) {
      mutate();
      resetWebappRefresh(session.id);
    }
  }, [
    webappNeedsRefresh,
    isFullyOpen,
    mutate,
    session?.id,
    resetWebappRefresh,
  ]);

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
        "absolute flex flex-col border rounded-12 border-border-01 bg-background-neutral-00 overflow-hidden transition-all duration-300 ease-in-out",
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
          activeOutputTab === "preview" &&
          displayUrl &&
          displayUrl.startsWith("http")
            ? displayUrl
            : null
        }
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

interface UrlBarProps {
  displayUrl: string;
  showNavigation?: boolean;
  canGoBack?: boolean;
  canGoForward?: boolean;
  onBack?: () => void;
  onForward?: () => void;
  previewUrl?: string | null;
}

/**
 * UrlBar - Chrome-style URL/status bar below tabs
 * Shows the current URL/path based on active tab or file preview
 * Optionally shows back/forward navigation buttons
 * For Preview tab, shows a button to open the URL in a new browser tab
 */
function UrlBar({
  displayUrl,
  showNavigation = false,
  canGoBack = false,
  canGoForward = false,
  onBack,
  onForward,
  previewUrl,
}: UrlBarProps) {
  const handleOpenInNewTab = () => {
    if (previewUrl) {
      window.open(previewUrl, "_blank", "noopener,noreferrer");
    }
  };

  return (
    <div className="px-3 pb-2">
      <div className="flex items-center gap-1">
        {/* Navigation buttons */}
        {showNavigation && (
          <div className="flex items-center gap-0.5">
            <button
              onClick={onBack}
              disabled={!canGoBack}
              className={cn(
                "p-1.5 rounded-full transition-colors",
                canGoBack
                  ? "hover:bg-background-tint-03 text-text-03"
                  : "text-text-02 cursor-not-allowed"
              )}
              aria-label="Go back"
            >
              <SvgArrowLeft size={16} />
            </button>
            <button
              onClick={onForward}
              disabled={!canGoForward}
              className={cn(
                "p-1.5 rounded-full transition-colors",
                canGoForward
                  ? "hover:bg-background-tint-03 text-text-03"
                  : "text-text-02 cursor-not-allowed"
              )}
              aria-label="Go forward"
            >
              <SvgArrowRight size={16} />
            </button>
          </div>
        )}
        {/* URL display */}
        <div className="flex-1 flex items-center px-3 py-1.5 bg-background-tint-02 rounded-full gap-2">
          {/* Open in new tab button - only shown for Preview tab with valid URL */}
          {previewUrl && (
            <SimpleTooltip tooltip="open in a new tab" delayDuration={200}>
              <button
                onClick={handleOpenInNewTab}
                className="flex-shrink-0 p-0.5 rounded transition-colors hover:bg-background-tint-03 text-text-03"
                aria-label="open in a new tab"
              >
                <SvgExternalLink size={14} />
              </button>
            </SimpleTooltip>
          )}
          <Text secondaryBody text03 className="truncate">
            {displayUrl}
          </Text>
        </div>
      </div>
    </div>
  );
}

interface PreviewTabProps {
  webappUrl: string | null;
}

/**
 * PreviewTab - Shows the webapp iframe preview
 *
 * States:
 * - No webapp URL yet: Shows blank dark background while SWR fetches
 * - Has webapp URL: Shows iframe with crossfade from blank background
 */
function PreviewTab({ webappUrl }: PreviewTabProps) {
  const [iframeLoaded, setIframeLoaded] = useState(false);

  // Reset loaded state when URL changes
  useEffect(() => {
    setIframeLoaded(false);
  }, [webappUrl]);

  // Base background shown while loading or when no webapp exists yet
  return (
    <div className="h-full flex flex-col">
      <div className="flex-1 p-3 relative">
        {/* Base dark background - always present, visible when no iframe or iframe loading */}
        <div
          className={cn(
            "absolute inset-0 rounded-b-08 bg-neutral-950",
            "transition-opacity duration-300",
            iframeLoaded ? "opacity-0 pointer-events-none" : "opacity-100"
          )}
        />

        {/* Iframe - fades in when loaded */}
        {webappUrl && (
          <iframe
            src={webappUrl}
            onLoad={() => setIframeLoaded(true)}
            className={cn(
              "absolute inset-0 w-full h-full rounded-b-08 bg-neutral-950",
              "transition-opacity duration-300",
              iframeLoaded ? "opacity-100" : "opacity-0"
            )}
            sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-popups-to-escape-sandbox allow-top-navigation-by-user-activation"
            title="Web App Preview"
          />
        )}
      </div>
    </div>
  );
}

interface ImagePreviewProps {
  src: string;
  fileName: string;
}

/**
 * ImagePreview - Displays images with loading and error states
 * Includes proper accessibility attributes
 */
function ImagePreview({ src, fileName }: ImagePreviewProps) {
  const [imageLoading, setImageLoading] = useState(true);
  const [imageError, setImageError] = useState(false);

  // Extract just the filename from path for better alt text
  const displayName = fileName.split("/").pop() || fileName;

  // Reset loading state when src changes
  useEffect(() => {
    setImageLoading(true);
    setImageError(false);
  }, [src]);

  if (imageError) {
    return (
      <Section
        height="full"
        alignItems="center"
        justifyContent="center"
        padding={2}
      >
        <SvgImage size={48} className="stroke-text-02" />
        <Text headingH3 text03>
          Failed to load image
        </Text>
        <Text secondaryBody text02>
          The image could not be displayed
        </Text>
      </Section>
    );
  }

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <div className="flex-1 flex items-center justify-center p-4">
        {imageLoading && (
          <div className="absolute">
            <Text secondaryBody text03>
              Loading image...
            </Text>
          </div>
        )}
        <img
          src={src}
          alt={displayName}
          role="img"
          aria-label={`Preview of ${displayName}`}
          className={cn(
            "max-w-full max-h-full object-contain transition-opacity",
            imageLoading ? "opacity-0" : "opacity-100"
          )}
          onLoad={() => setImageLoading(false)}
          onError={() => {
            setImageLoading(false);
            setImageError(true);
          }}
        />
      </div>
    </div>
  );
}

interface FilePreviewContentProps {
  sessionId: string;
  filePath: string;
}

/**
 * FilePreviewContent - Displays file content in a scrollable monospace view
 * Fetches content via SWR and displays loading/error/content states
 */
function FilePreviewContent({ sessionId, filePath }: FilePreviewContentProps) {
  const { data, error, isLoading } = useSWR(
    `/api/build/sessions/${sessionId}/artifacts/${filePath}`,
    () => fetchFileContent(sessionId, filePath),
    {
      revalidateOnFocus: false,
      dedupingInterval: 5000,
    }
  );

  if (isLoading) {
    return (
      <Section
        height="full"
        alignItems="center"
        justifyContent="center"
        padding={2}
      >
        <Text secondaryBody text03>
          Loading file...
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
        <SvgFileText size={48} className="stroke-text-02" />
        <Text headingH3 text03>
          Error loading file
        </Text>
        <Text secondaryBody text02>
          {error.message}
        </Text>
      </Section>
    );
  }

  if (!data) {
    return (
      <Section
        height="full"
        alignItems="center"
        justifyContent="center"
        padding={2}
      >
        <Text secondaryBody text03>
          No content
        </Text>
      </Section>
    );
  }

  // Display error if image is too large or had issues
  if (data.error) {
    return (
      <Section
        height="full"
        alignItems="center"
        justifyContent="center"
        padding={2}
      >
        <SvgFileText size={48} className="stroke-text-02" />
        <Text headingH3 text03>
          Cannot preview file
        </Text>
        <Text secondaryBody text02 className="text-center max-w-md">
          {data.error}
        </Text>
      </Section>
    );
  }

  // Display images
  if (data.isImage) {
    return <ImagePreview src={data.content} fileName={filePath} />;
  }

  // Display text content
  return (
    <div className="h-full flex flex-col">
      <div className="flex-1 overflow-auto p-4">
        <pre className="font-mono text-sm text-text-04 whitespace-pre-wrap break-words">
          {data.content}
        </pre>
      </div>
    </div>
  );
}

/**
 * InlineFilePreview - Simple file preview for pre-provisioned mode
 * Same as FilePreviewContent but without the full height wrapper
 */
function InlineFilePreview({
  sessionId,
  filePath,
}: {
  sessionId: string;
  filePath: string;
}) {
  const { data, error, isLoading } = useSWR(
    `/api/build/sessions/${sessionId}/artifacts/${filePath}`,
    () => fetchFileContent(sessionId, filePath),
    {
      revalidateOnFocus: false,
      dedupingInterval: 5000,
    }
  );

  if (isLoading) {
    return (
      <div className="p-4">
        <Text secondaryBody text03>
          Loading file...
        </Text>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4">
        <Text secondaryBody text02>
          Error: {error.message}
        </Text>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="p-4">
        <Text secondaryBody text03>
          No content
        </Text>
      </div>
    );
  }

  // Display error if image is too large or had issues
  if (data.error) {
    return (
      <div className="p-4">
        <Text secondaryBody text02 className="text-center">
          {data.error}
        </Text>
      </div>
    );
  }

  // Display images
  if (data.isImage) {
    return <ImagePreview src={data.content} fileName={filePath} />;
  }

  // Display text content
  return (
    <div className="p-4">
      <pre className="font-mono text-sm text-text-04 whitespace-pre-wrap break-words">
        {data.content}
      </pre>
    </div>
  );
}

interface FilesTabProps {
  sessionId: string | null;
  onFileClick?: (path: string, fileName: string) => void;
  /** True when showing pre-provisioned sandbox (read-only, no file clicks) */
  isPreProvisioned?: boolean;
  /** True when sandbox is still being provisioned */
  isProvisioning?: boolean;
}

function FilesTab({
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
  const { data: rootListing, error } = useSWR(
    sessionId ? `/api/build/sessions/${sessionId}/files?path=` : null,
    () => (sessionId ? fetchDirectoryListing(sessionId, "") : null),
    {
      revalidateOnFocus: false,
      dedupingInterval: 2000,
    }
  );

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
              ) : entry.mime_type?.startsWith("image/") ? (
                <SvgImage
                  size={16}
                  className="stroke-text-03 flex-shrink-0 mx-1"
                />
              ) : (
                <SvgFileText
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

interface ArtifactsTabProps {
  artifacts: Artifact[];
  sessionId: string | null;
}

function ArtifactsTab({ artifacts, sessionId }: ArtifactsTabProps) {
  // Filter to only show webapp artifacts
  const webappArtifacts = artifacts.filter(
    (a) => a.type === "nextjs_app" || a.type === "web_app"
  );

  const handleDownload = () => {
    if (!sessionId) return;

    // Trigger download by creating a link and clicking it
    const downloadUrl = `/api/build/sessions/${sessionId}/webapp/download`;
    const link = document.createElement("a");
    link.href = downloadUrl;
    link.download = ""; // Let the server set the filename
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  if (!sessionId || webappArtifacts.length === 0) {
    return (
      <Section
        height="full"
        alignItems="center"
        justifyContent="center"
        padding={2}
      >
        <SvgGlobe size={48} className="stroke-text-02" />
        <Text headingH3 text03>
          No web apps yet
        </Text>
        <Text secondaryBody text02>
          Web apps created during the build will appear here
        </Text>
      </Section>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Webapp Artifact List */}
      <div className="flex-1 overflow-auto overlay-scrollbar">
        <div className="divide-y divide-border-01">
          {webappArtifacts.map((artifact) => {
            return (
              <div
                key={artifact.id}
                className="flex items-center gap-3 p-3 hover:bg-background-tint-01 transition-colors"
              >
                <SvgGlobe size={24} className="stroke-text-03 flex-shrink-0" />

                <div className="flex-1 min-w-0">
                  <Text secondaryBody text04 className="truncate">
                    {artifact.name}
                  </Text>
                  <Text secondaryBody text02>
                    Next.js Application
                  </Text>
                </div>

                <div className="flex items-center gap-2">
                  <Button
                    tertiary
                    action
                    leftIcon={SvgDownloadCloud}
                    onClick={handleDownload}
                  >
                    Download
                  </Button>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
