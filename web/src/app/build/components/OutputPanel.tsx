"use client";

import { useState, memo } from "react";
import { cn } from "@/lib/utils";
import { useBuildSession } from "@/app/build/hooks/useBuildSession";
import Text from "@/refresh-components/texts/Text";
import IconButton from "@/refresh-components/buttons/IconButton";
import Button from "@/refresh-components/buttons/Button";
import {
  SvgGlobe,
  SvgHardDrive,
  SvgFiles,
  SvgX,
  SvgExternalLink,
} from "@opal/icons";

type TabId = "preview" | "files" | "artifacts";

interface TabConfig {
  id: TabId;
  label: string;
  icon: React.FC<{ className?: string }>;
}

const TABS: TabConfig[] = [
  { id: "preview", label: "Preview", icon: SvgGlobe },
  { id: "files", label: "Files", icon: SvgHardDrive },
  { id: "artifacts", label: "Artifacts", icon: SvgFiles },
];

interface BuildOutputPanelProps {
  onClose: () => void;
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
const BuildOutputPanel = memo(({ onClose }: BuildOutputPanelProps) => {
  const { session } = useBuildSession();
  const [activeTab, setActiveTab] = useState<TabId>("preview");

  const hasWebapp = session.artifacts.some((a) => a.type === "nextjs_app");
  const webappUrl = session.webappUrl;

  return (
    <div className="h-full flex flex-col bg-background-neutral-00">
      {/* Header with tabs */}
      <div className="flex flex-row items-center justify-between px-3 py-2 border-b border-border-01">
        <div className="flex flex-row items-center gap-2">
          {TABS.map((tab) => {
            const Icon = tab.icon;
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={cn(
                  "flex flex-row items-center gap-1.5 px-3 py-2",
                  "border-b-2 transition-colors",
                  isActive
                    ? "border-theme-primary-05 text-text-05"
                    : "border-transparent text-text-03 hover:text-text-04"
                )}
              >
                <Icon className="size-4" />
                <Text mainUiAction>{tab.label}</Text>
              </button>
            );
          })}
        </div>
        <IconButton
          icon={SvgX}
          tertiary
          onClick={onClose}
          tooltip="Close panel"
        />
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-auto">
        {activeTab === "preview" && (
          <PreviewTab webappUrl={webappUrl} hasWebapp={hasWebapp} />
        )}
        {activeTab === "files" && <FilesTab sessionId={session.id} />}
        {activeTab === "artifacts" && (
          <ArtifactsTab artifacts={session.artifacts} sessionId={session.id} />
        )}
      </div>
    </div>
  );
});

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
      <div className="h-full flex flex-col items-center justify-center p-8 text-center">
        <SvgGlobe className="size-12 stroke-text-02 mb-4" />
        <Text headingH3 text03>
          No preview available
        </Text>
        <Text secondaryBody text02 className="mt-2">
          Build a web app to see a live preview here
        </Text>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      <div className="flex flex-row items-center justify-between p-3 border-b border-border-01">
        <Text secondaryBody text03>
          Live Preview
        </Text>
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
  if (!sessionId) {
    return (
      <div className="h-full flex flex-col items-center justify-center p-8 text-center">
        <SvgHardDrive className="size-12 stroke-text-02 mb-4" />
        <Text headingH3 text03>
          No files yet
        </Text>
        <Text secondaryBody text02 className="mt-2">
          Files created during the build will appear here
        </Text>
      </div>
    );
  }

  // TODO: Implement file browser
  return (
    <div className="p-3">
      <Text secondaryBody text03>
        File browser - session: {sessionId}
      </Text>
    </div>
  );
}

interface ArtifactsTabProps {
  artifacts: { id: string; type: string; name: string; path: string }[];
  sessionId: string | null;
}

function ArtifactsTab({ artifacts, sessionId }: ArtifactsTabProps) {
  if (!sessionId || artifacts.length === 0) {
    return (
      <div className="h-full flex flex-col items-center justify-center p-8 text-center">
        <SvgFiles className="size-12 stroke-text-02 mb-4" />
        <Text headingH3 text03>
          No artifacts yet
        </Text>
        <Text secondaryBody text02 className="mt-2">
          Artifacts created during the build will appear here
        </Text>
      </div>
    );
  }

  // TODO: Implement artifact list
  return (
    <div className="p-3">
      <Text secondaryBody text03>
        {artifacts.length} artifact(s) created
      </Text>
    </div>
  );
}
