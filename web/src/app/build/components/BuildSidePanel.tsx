"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import Button from "@/refresh-components/buttons/Button";
import {
  SvgGlobe,
  SvgExternalLink,
  SvgHardDrive,
  SvgFiles,
  SvgX,
} from "@opal/icons";
import { getWebappUrl, ArtifactInfo } from "@/lib/build/client";
import FileBrowser from "./FileBrowser";
import ArtifactList from "./ArtifactList";

type TabId = "preview" | "files" | "artifacts";

interface Tab {
  id: TabId;
  label: string;
  icon: React.FC<{ className?: string }>;
}

const TABS: Tab[] = [
  { id: "preview", label: "Preview", icon: SvgGlobe },
  { id: "files", label: "Files", icon: SvgHardDrive },
  { id: "artifacts", label: "Artifacts", icon: SvgFiles },
];

interface BuildSidePanelProps {
  sessionId: string | null;
  artifacts: ArtifactInfo[];
  hasWebapp: boolean;
  onClose?: () => void;
}

export default function BuildSidePanel({
  sessionId,
  artifacts,
  hasWebapp,
  onClose,
}: BuildSidePanelProps) {
  const [activeTab, setActiveTab] = useState<TabId>("preview");
  const fileArtifacts = artifacts.filter((a) => a.artifact_type !== "webapp");

  if (!sessionId) {
    return (
      <div className="h-full flex flex-col items-center justify-center p-8 text-center">
        <SvgHardDrive className="size-12 stroke-text-02 mb-4" />
        <Text headingH3 text03>
          No active session
        </Text>
        <Text secondaryBody text02 className="mt-2">
          Start a task to view files and preview
        </Text>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col bg-background-neutral-00">
      {/* Header with tabs */}
      <div className="flex flex-row items-center justify-between border-b border-border-01 px-2">
        <div className="flex flex-row">
          {TABS.map((tab) => {
            const Icon = tab.icon;
            const isActive = activeTab === tab.id;

            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={cn(
                  "flex flex-row items-center gap-1.5 px-3 py-2.5",
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
        {onClose && (
          <button
            onClick={onClose}
            className="p-1.5 rounded-08 hover:bg-background-neutral-01 transition-colors"
          >
            <SvgX className="size-4 stroke-text-03" />
          </button>
        )}
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-auto">
        {activeTab === "preview" && (
          <div className="h-full flex flex-col">
            <div className="flex flex-row items-center justify-between p-2 border-b border-border-01">
              <Text secondaryBody text03>
                Live Preview
              </Text>
              <a
                href={getWebappUrl()}
                target="_blank"
                rel="noopener noreferrer"
              >
                <Button action tertiary rightIcon={SvgExternalLink}>
                  Open
                </Button>
              </a>
            </div>
            <div className="flex-1 p-2">
              <iframe
                src={getWebappUrl()}
                className="w-full h-full rounded-08 border border-border-01 bg-white"
                sandbox="allow-scripts allow-same-origin allow-forms"
                title="Web App Preview"
              />
            </div>
          </div>
        )}

        {activeTab === "files" && sessionId && (
          <div className="p-2">
            <FileBrowser sessionId={sessionId} />
          </div>
        )}

        {activeTab === "artifacts" && sessionId && (
          <div className="p-2">
            <ArtifactList artifacts={artifacts} sessionId={sessionId} />
          </div>
        )}
      </div>
    </div>
  );
}
