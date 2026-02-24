"use client";

import { useCallback, useEffect, useState } from "react";
import useSWR from "swr";
import Text from "@/refresh-components/texts/Text";
import Button from "@/refresh-components/buttons/Button";
import {
  SvgGlobe,
  SvgDownloadCloud,
  SvgFolder,
  SvgFiles,
  SvgChevronDown,
  SvgChevronRight,
} from "@opal/icons";
import { Section } from "@/layouts/general-layouts";
import { Artifact } from "@/app/craft/hooks/useBuildSessionStore";
import { useFilesNeedsRefresh } from "@/app/craft/hooks/useBuildSessionStore";
import {
  fetchDirectoryListing,
  downloadArtifactFile,
  downloadDirectory,
} from "@/app/craft/services/apiServices";
import { FileSystemEntry } from "@/app/craft/types/streamingTypes";
import { getFileIcon } from "@/lib/utils";
import { cn } from "@/lib/utils";

interface ArtifactsTabProps {
  artifacts: Artifact[];
  sessionId: string | null;
}

export default function ArtifactsTab({
  artifacts,
  sessionId,
}: ArtifactsTabProps) {
  const webappArtifacts = artifacts.filter(
    (a) => a.type === "nextjs_app" || a.type === "web_app"
  );

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

  // Filter out "web" directory (shown as webapp artifact)
  const rawEntries = (outputsListing?.entries ?? []).filter(
    (entry) => entry.name !== "web"
  );

  // Filter out empty directories
  const [outputEntries, setOutputEntries] = useState<FileSystemEntry[]>([]);

  useEffect(() => {
    if (!sessionId || rawEntries.length === 0) {
      setOutputEntries([]);
      return;
    }

    let cancelled = false;

    async function filterEmptyDirs() {
      const results = await Promise.all(
        rawEntries.map(async (entry) => {
          if (!entry.is_directory) return entry;
          try {
            const listing = await fetchDirectoryListing(sessionId!, entry.path);
            if (listing && listing.entries.length > 0) return entry;
          } catch {
            return entry;
          }
          return null;
        })
      );
      if (!cancelled) {
        setOutputEntries(
          results.filter((e): e is FileSystemEntry => e !== null)
        );
      }
    }

    filterEmptyDirs();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, JSON.stringify(rawEntries.map((e) => e.path))]);

  const handleWebappDownload = () => {
    if (!sessionId) return;
    const link = document.createElement("a");
    link.href = `/api/build/sessions/${sessionId}/webapp/download`;
    link.download = "";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const handleOutputDownload = useCallback(
    (path: string, isDirectory: boolean) => {
      if (!sessionId) return;
      if (isDirectory) {
        downloadDirectory(sessionId, path);
      } else {
        downloadArtifactFile(sessionId, path);
      }
    },
    [sessionId]
  );

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
          {outputEntries.map((entry) => (
            <OutputEntryRow
              key={entry.path}
              entry={entry}
              sessionId={sessionId!}
              depth={0}
              onDownload={handleOutputDownload}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

interface OutputEntryRowProps {
  entry: FileSystemEntry;
  sessionId: string;
  depth: number;
  onDownload: (path: string, isDirectory: boolean) => void;
}

function OutputEntryRow({
  entry,
  sessionId,
  depth,
  onDownload,
}: OutputEntryRowProps) {
  const [expanded, setExpanded] = useState(false);
  const [children, setChildren] = useState<FileSystemEntry[]>([]);
  const [loaded, setLoaded] = useState(false);

  const toggleExpand = useCallback(async () => {
    if (!entry.is_directory) return;

    if (!loaded) {
      const listing = await fetchDirectoryListing(sessionId, entry.path);
      if (listing) {
        setChildren(listing.entries);
      }
      setLoaded(true);
    }
    setExpanded((prev) => !prev);
  }, [entry.is_directory, entry.path, sessionId, loaded]);

  const FileIcon = entry.is_directory ? SvgFolder : getFileIcon(entry.name);
  const paddingLeft = depth * 20;

  return (
    <>
      <div
        className={cn(
          "flex items-center gap-3 p-3 hover:bg-background-tint-01 transition-colors",
          entry.is_directory && "cursor-pointer"
        )}
        style={{ paddingLeft: 12 + paddingLeft }}
        onClick={entry.is_directory ? toggleExpand : undefined}
      >
        {entry.is_directory ? (
          expanded ? (
            <SvgChevronDown
              size={16}
              className="stroke-text-03 flex-shrink-0"
            />
          ) : (
            <SvgChevronRight
              size={16}
              className="stroke-text-03 flex-shrink-0"
            />
          )
        ) : (
          <div className="w-4 flex-shrink-0" />
        )}

        <FileIcon size={20} className="stroke-text-02 flex-shrink-0" />

        <div className="flex-1 min-w-0 flex items-center gap-2">
          <Text secondaryBody text04 className="truncate">
            {entry.name}
          </Text>
          {!entry.is_directory && entry.size !== null ? (
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
            onClick={(e) => {
              e.stopPropagation();
              onDownload(entry.path, entry.is_directory);
            }}
          >
            Download
          </Button>
        </div>
      </div>

      {expanded &&
        children.map((child) => (
          <OutputEntryRow
            key={child.path}
            entry={child}
            sessionId={sessionId}
            depth={depth + 1}
            onDownload={onDownload}
          />
        ))}
    </>
  );
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
