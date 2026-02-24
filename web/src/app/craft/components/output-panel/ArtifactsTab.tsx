"use client";

import useSWR from "swr";
import Text from "@/refresh-components/texts/Text";
import Button from "@/refresh-components/buttons/Button";
import { SvgGlobe, SvgDownloadCloud, SvgFolder, SvgFiles } from "@opal/icons";
import { Section } from "@/layouts/general-layouts";
import { Artifact } from "@/app/craft/hooks/useBuildSessionStore";
import { useFilesNeedsRefresh } from "@/app/craft/hooks/useBuildSessionStore";
import {
  fetchDirectoryListing,
  downloadArtifactFile,
  downloadDirectory,
} from "@/app/craft/services/apiServices";
import { getFileIcon } from "@/lib/utils";

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

  // Fetch top-level items in outputs/ directory
  const filesNeedsRefresh = useFilesNeedsRefresh();
  const { data: outputsListing } = useSWR(
    sessionId
      ? [
          `/api/build/sessions/${sessionId}/files?path=outputs`,
          filesNeedsRefresh,
        ]
      : null,
    () => (sessionId ? fetchDirectoryListing(sessionId, "outputs") : null),
    {
      revalidateOnFocus: false,
      dedupingInterval: 2000,
    }
  );

  // Filter out the "web" directory since it's already shown as a webapp artifact
  const outputEntries = (outputsListing?.entries ?? []).filter(
    (entry) => entry.name !== "web"
  );

  const handleWebappDownload = () => {
    if (!sessionId) return;
    const link = document.createElement("a");
    link.href = `/api/build/sessions/${sessionId}/webapp/download`;
    link.download = "";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const handleOutputDownload = (path: string, isDirectory: boolean) => {
    if (!sessionId) return;
    if (isDirectory) {
      downloadDirectory(sessionId, path);
    } else {
      downloadArtifactFile(sessionId, path);
    }
  };

  const hasWebapps = webappArtifacts.length > 0;
  const hasOutputFiles = outputEntries.length > 0;

  if (!sessionId || (!hasWebapps && !hasOutputFiles)) {
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
          Output files and web apps will appear here
        </Text>
      </Section>
    );
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-auto overlay-scrollbar">
        <div className="divide-y divide-border-01">
          {/* Webapp Artifacts */}
          {webappArtifacts.map((artifact) => (
            <div
              key={artifact.id}
              className="flex items-center gap-3 p-3 hover:bg-background-tint-01 transition-colors"
            >
              <SvgGlobe size={24} className="stroke-text-02 flex-shrink-0" />

              <div className="flex-1 min-w-0 flex items-center gap-2">
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
                  onClick={handleWebappDownload}
                >
                  Download
                </Button>
              </div>
            </div>
          ))}

          {/* Output Files & Folders */}
          {outputEntries.map((entry) => {
            const FileIcon = entry.is_directory
              ? SvgFolder
              : getFileIcon(entry.name);
            return (
              <div
                key={entry.path}
                className="flex items-center gap-3 p-3 hover:bg-background-tint-01 transition-colors"
              >
                <FileIcon size={24} className="stroke-text-02 flex-shrink-0" />

                <div className="flex-1 min-w-0 flex items-center gap-2">
                  <Text secondaryBody text04 className="truncate">
                    {entry.name}
                  </Text>
                  {entry.is_directory ? (
                    <Text secondaryBody text02>
                      Folder
                    </Text>
                  ) : entry.size !== null ? (
                    <Text secondaryBody text02>
                      {formatFileSize(entry.size)}
                    </Text>
                  ) : null}
                </div>

                <div className="flex items-center gap-2">
                  <Button
                    tertiary
                    action
                    leftIcon={SvgDownloadCloud}
                    onClick={() =>
                      handleOutputDownload(entry.path, entry.is_directory)
                    }
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

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
