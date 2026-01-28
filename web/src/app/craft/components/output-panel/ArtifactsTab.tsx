"use client";

import Text from "@/refresh-components/texts/Text";
import Button from "@/refresh-components/buttons/Button";
import { SvgGlobe, SvgDownloadCloud } from "@opal/icons";
import { Section } from "@/layouts/general-layouts";
import { Artifact } from "@/app/craft/hooks/useBuildSessionStore";

interface ArtifactsTabProps {
  artifacts: Artifact[];
  sessionId: string | null;
}

export default function ArtifactsTab({
  artifacts,
  sessionId,
}: ArtifactsTabProps) {
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
