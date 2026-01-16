"use client";

import Text from "@/refresh-components/texts/Text";
import Button from "@/refresh-components/buttons/Button";
import { SvgFiles, SvgDownloadCloud } from "@opal/icons";
import { ArtifactInfo, getArtifactUrl } from "@/lib/build/client";

interface ArtifactListProps {
  artifacts: ArtifactInfo[];
  sessionId: string;
}

export default function ArtifactList({
  artifacts,
  sessionId,
}: ArtifactListProps) {
  const fileArtifacts = artifacts.filter((a) => a.artifact_type !== "webapp");

  if (fileArtifacts.length === 0) {
    return (
      <div className="p-4 text-center">
        <Text secondaryBody text03>
          No artifacts generated yet
        </Text>
      </div>
    );
  }

  return (
    <div className="border border-border-01 rounded-08 overflow-hidden">
      <div className="p-2 bg-background-neutral-01 flex flex-row items-center gap-1.5">
        <SvgFiles className="size-4 stroke-text-03" />
        <Text mainUiAction text03>
          Generated Files
        </Text>
      </div>
      <ul className="divide-y divide-border-01 max-h-[50vh] overflow-auto">
        {fileArtifacts.map((artifact) => (
          <li
            key={artifact.path}
            className="p-2 flex flex-row items-center justify-between gap-2 hover:bg-background-neutral-01 transition-colors"
          >
            <Text mainContentMono text04 className="truncate flex-1 text-sm">
              {artifact.filename}
            </Text>
            <a
              href={getArtifactUrl(sessionId, artifact.path)}
              download={artifact.filename}
            >
              <Button action tertiary leftIcon={SvgDownloadCloud}>
                Download
              </Button>
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}
