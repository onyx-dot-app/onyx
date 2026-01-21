"use client";

import { memo, useState } from "react";
import useSWR from "swr";
import { useSession, Artifact } from "@/app/build/hooks/useBuildSessionStore";
import {
  fetchWebappInfo,
  fetchDirectoryListing,
  fetchArtifacts,
} from "@/app/build/services/apiServices";
import { FileSystemEntry } from "@/app/build/services/buildStreamingModels";
import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import Button from "@/refresh-components/buttons/Button";
import {
  SvgGlobe,
  SvgHardDrive,
  SvgFiles,
  SvgExternalLink,
  SvgFolder,
  SvgFileText,
  SvgChevronLeft,
  SvgDownloadCloud,
} from "@opal/icons";
import { Section } from "@/layouts/general-layouts";
import { IconProps } from "@opal/types";

type TabValue = "preview" | "files" | "artifacts";

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
const BuildOutputPanel = memo(
  ({ onClose: _onClose, isOpen }: BuildOutputPanelProps) => {
    const session = useSession();
    const [activeTab, setActiveTab] = useState<TabValue>("preview");

    // Fetch webapp info from dedicated endpoint
    // Only fetch for real sessions (not temp-* IDs) that are loaded
    const shouldFetchWebapp =
      session?.id &&
      !session.id.startsWith("temp-") &&
      session.status !== "creating";

    const { data: webappInfo } = useSWR(
      shouldFetchWebapp ? `/api/build/sessions/${session.id}/webapp` : null,
      () => (session?.id ? fetchWebappInfo(session.id) : null),
      {
        refreshInterval: 5000, // Refresh every 5 seconds to catch when webapp starts
        revalidateOnFocus: true,
      }
    );

    const hasWebapp = webappInfo?.has_webapp ?? false;
    const webappUrl = webappInfo?.webapp_url ?? null;

    // Fetch artifacts - poll every 5 seconds when on artifacts tab
    const shouldFetchArtifacts =
      session?.id &&
      !session.id.startsWith("temp-") &&
      session.status !== "creating" &&
      activeTab === "artifacts";

    const { data: polledArtifacts } = useSWR(
      shouldFetchArtifacts
        ? `/api/build/sessions/${session.id}/artifacts`
        : null,
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
          "h-full flex flex-col border py-4 rounded-12 border-border-01 bg-background-neutral-00 transition-all duration-300 ease-in-out overflow-hidden",
          isOpen ? "w-1/2 opacity-100 px-4" : "w-0 opacity-0"
        )}
      >
        {/* Tab List */}
        <div className="flex w-full rounded-t-08 bg-background-tint-03">
          {tabs.map((tab) => {
            const Icon = tab.icon;
            const isActive = activeTab === tab.value;
            return (
              <button
                key={tab.value}
                onClick={() => setActiveTab(tab.value)}
                className={cn(
                  "flex-1 inline-flex items-center justify-center gap-2 rounded-t-08 p-2",
                  isActive
                    ? "bg-background-neutral-00 text-text-04 shadow-01 border"
                    : "text-text-03 bg-transparent border border-transparent"
                )}
              >
                <Icon size={16} className="stroke-text-03" />
                <Text>{tab.label}</Text>
              </button>
            );
          })}
        </div>

        {/* Tab Content */}
        <div className="flex-1 min-h-0">
          <div className="h-full border-x border-b border-border-01 rounded-b-08">
            {activeTab === "preview" && (
              <PreviewTab webappUrl={webappUrl} hasWebapp={hasWebapp} />
            )}
            {activeTab === "files" && (
              <FilesTab sessionId={session?.id ?? null} />
            )}
            {activeTab === "artifacts" && (
              <ArtifactsTab
                artifacts={artifacts}
                sessionId={session?.id ?? null}
              />
            )}
          </div>
        </div>
      </div>
    );
  }
);

BuildOutputPanel.displayName = "BuildOutputPanel";

export default BuildOutputPanel;

// ============================================================================
// Tab Content Components
// ============================================================================

interface PreviewTabProps {
  webappUrl: string | null;
  hasWebapp: boolean;
}

function PreviewTab({ webappUrl, hasWebapp }: PreviewTabProps) {
  if (!hasWebapp) {
    return (
      <Section
        height="full"
        alignItems="center"
        justifyContent="center"
        padding={2}
      >
        <SvgGlobe size={48} className="stroke-text-02" />
        <Text headingH3 text03>
          No preview available
        </Text>
        <Text secondaryBody text02>
          Build a web app to see a live preview here
        </Text>
      </Section>
    );
  }

  return (
    <div className="h-full flex flex-col">
      <div className="flex flex-row items-center justify-between p-3 border-b border-border-01">
        {webappUrl && (
          <a href={webappUrl} target="_blank" rel="noopener noreferrer">
            <Button action tertiary rightIcon={SvgExternalLink}>
              Open
            </Button>
          </a>
        )}
      </div>
      <div className="flex-1 p-3">
        {webappUrl && (
          <iframe
            src={webappUrl}
            className="w-full h-full rounded-08 border border-border-01 bg-white"
            sandbox="allow-scripts allow-same-origin allow-forms"
            title="Web App Preview"
          />
        )}
      </div>
    </div>
  );
}

interface FilesTabProps {
  sessionId: string | null;
}

function FilesTab({ sessionId }: FilesTabProps) {
  const [currentPath, setCurrentPath] = useState("");

  const { data: listing, error } = useSWR(
    sessionId
      ? `/api/build/sessions/${sessionId}/files?path=${currentPath}`
      : null,
    () => (sessionId ? fetchDirectoryListing(sessionId, currentPath) : null),
    {
      revalidateOnFocus: false,
      dedupingInterval: 2000,
    }
  );

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
          No files yet
        </Text>
        <Text secondaryBody text02>
          Files created during the build will appear here
        </Text>
      </Section>
    );
  }

  const handleNavigate = (entry: FileSystemEntry) => {
    if (entry.is_directory) {
      setCurrentPath(entry.path);
    }
  };

  const handleBack = () => {
    const parts = currentPath.split("/").filter(Boolean);
    parts.pop();
    setCurrentPath(parts.join("/"));
  };

  const formatFileSize = (bytes: number | null): string => {
    if (bytes === null) return "";
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

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

  if (!listing) {
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

  return (
    <div className="flex flex-col h-full">
      {/* Breadcrumb / Navigation */}
      <div className="flex items-center gap-2 p-3 border-b border-border-01">
        {currentPath && (
          <button
            onClick={handleBack}
            className="p-1 hover:bg-background-tint-02 rounded"
          >
            <SvgChevronLeft size={16} className="stroke-text-03" />
          </button>
        )}
        <Text secondaryBody text03>
          /{currentPath || ""}
        </Text>
      </div>

      {/* File List */}
      <div className="flex-1 overflow-auto">
        {listing.entries.length === 0 ? (
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
          <div className="divide-y divide-border-01">
            {listing.entries.map((entry) => (
              <button
                key={entry.path}
                onClick={() => handleNavigate(entry)}
                className={cn(
                  "w-full flex items-center gap-3 p-3 hover:bg-background-tint-02 transition-colors",
                  !entry.is_directory && "cursor-default"
                )}
              >
                {entry.is_directory ? (
                  <SvgFolder
                    size={20}
                    className="stroke-text-03 flex-shrink-0"
                  />
                ) : (
                  <SvgFileText
                    size={20}
                    className="stroke-text-03 flex-shrink-0"
                  />
                )}
                <div className="flex-1 min-w-0 text-left">
                  <Text secondaryBody text04 className="truncate">
                    {entry.name}
                  </Text>
                  {!entry.is_directory && entry.size !== null && (
                    <Text text02>{formatFileSize(entry.size)}</Text>
                  )}
                </div>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
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
      {/* Header */}
      <div className="p-3 border-b border-border-01">
        <Text secondaryBody text03>
          {webappArtifacts.length} web app
          {webappArtifacts.length !== 1 ? "s" : ""}
        </Text>
      </div>

      {/* Webapp Artifact List */}
      <div className="flex-1 overflow-auto">
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
