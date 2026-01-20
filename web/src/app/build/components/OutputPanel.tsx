"use client";

import { memo, useState } from "react";
import { useSession, Artifact } from "@/app/build/hooks/useBuildSessionStore";
import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import Button from "@/refresh-components/buttons/Button";
import { SvgGlobe, SvgHardDrive, SvgFiles, SvgExternalLink } from "@opal/icons";
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

    const hasWebapp =
      session?.artifacts.some((a: Artifact) => a.type === "nextjs_app") ??
      false;
    const webappUrl = session?.webappUrl ?? null;

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
                artifacts={session?.artifacts ?? []}
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
  artifacts: Artifact[];
  sessionId: string | null;
}

function ArtifactsTab({ artifacts, sessionId }: ArtifactsTabProps) {
  if (!sessionId || artifacts.length === 0) {
    return (
      <Section
        height="full"
        alignItems="center"
        justifyContent="center"
        padding={2}
      >
        <SvgFiles size={48} className="stroke-text-02" />
        <Text headingH3 text03>
          No artifacts yet
        </Text>
        <Text secondaryBody text02>
          Artifacts created during the build will appear here
        </Text>
      </Section>
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
