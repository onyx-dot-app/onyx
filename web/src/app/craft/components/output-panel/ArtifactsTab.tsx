"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { Text, Button } from "@opal/components";
import {
  SvgGlobe,
  SvgDownloadCloud,
  SvgFolder,
  SvgFiles,
  SvgChevronDown,
  SvgChevronRight,
  SvgLoader,
} from "@opal/icons";
import { Section } from "@/layouts/general-layouts";
import {
  type Artifact,
  useBuildSessionStore,
} from "@/app/craft/hooks/useBuildSessionStore";
import {
  downloadArtifactFile,
  downloadDirectory,
} from "@/app/craft/services/apiServices";
import type { OutputFile } from "@/app/craft/types/streamingTypes";
import { formatBytes, getFileIcon } from "@/lib/utils";
import { clickOnKeyDown } from "@opal/utils";

interface ArtifactsTabProps {
  artifacts: Artifact[];
  sessionId: string | null;
  isActive?: boolean;
}

export default function ArtifactsTab({
  artifacts,
  sessionId,
  isActive = true,
}: ArtifactsTabProps) {
  const t = useTranslations("craft.artifactsTab");
  const webappArtifacts = artifacts.filter(
    (a) => a.type === "nextjs_app" || a.type === "web_app"
  );

  const setActiveOutputTab = useBuildSessionStore(
    (state) => state.setActiveOutputTab
  );
  const openFilePreview = useBuildSessionStore(
    (state) => state.openFilePreview
  );

  const handleWebappOpen = useCallback(() => {
    if (sessionId) setActiveOutputTab(sessionId, "preview");
  }, [sessionId, setActiveOutputTab]);

  const handleFileOpen = useCallback(
    (path: string, fileName: string) => {
      if (sessionId) openFilePreview(sessionId, path, fileName);
    },
    [sessionId, openFilePreview]
  );

  const inventory = useBuildSessionStore((state) =>
    sessionId ? state.sessions.get(sessionId)?.outputInventory : null
  );
  const inventoryStatus = useBuildSessionStore((state) =>
    sessionId ? state.sessions.get(sessionId)?.outputInventoryStatus : undefined
  );
  const refreshInventory = useBuildSessionStore(
    (state) => state.refreshOutputInventory
  );
  useEffect(() => {
    if (!sessionId || !isActive) return;
    const session = useBuildSessionStore.getState().sessions.get(sessionId);
    void refreshInventory(sessionId, {
      silent: !session?.activeTurnId && session?.status !== "running",
    });
  }, [sessionId, isActive, refreshInventory]);
  const outputEntries = useMemo(
    () => buildOutputTree(inventory ?? {}),
    [inventory]
  );
  const statusMessage =
    inventoryStatus === "error"
      ? t("status.error")
      : inventoryStatus === "partial"
        ? t("status.incomplete")
        : inventoryStatus === "loading"
          ? t("status.loading")
          : null;

  const handleWebappDownload = () => {
    if (!sessionId) return;
    const link = document.createElement("a");
    link.href = `/api/build/sessions/${sessionId}/webapp-download`;
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

  if (!sessionId || (!hasWebapps && !hasOutputFiles && !statusMessage)) {
    return (
      <Section
        height="full"
        alignItems="center"
        justifyContent="center"
        padding={8}
      >
        <SvgFiles size={48} className="stroke-text-02" />
        <Text font="heading-h3" color="text-03">
          {t("empty.title")}
        </Text>
        <Text font="secondary-body" color="text-02">
          {t("empty.description")}
        </Text>
      </Section>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {statusMessage && (
        <div role="status" className="flex items-center gap-2 p-3">
          {inventoryStatus === "loading" && (
            <SvgLoader size={16} className="animate-spin stroke-text-03" />
          )}
          <Text font="secondary-body" color="text-02">
            {statusMessage}
          </Text>
        </div>
      )}
      <div className="flex-1 overflow-auto overlay-scrollbar">
        <div className="divide-y divide-border-01">
          {/* Webapp Artifacts */}
          {webappArtifacts.map((artifact) => (
            // The row holds its own buttons, so it stays a div with button
            // semantics rather than a <button> wrapping a <button>.
            <div
              key={artifact.id}
              className="flex items-center gap-3 p-3 hover:bg-background-tint-01 transition-colors cursor-pointer"
              style={{ paddingInlineStart: 12 }}
              role="button"
              tabIndex={0}
              aria-label={t("openItem.ariaLabel", { name: artifact.name })}
              onKeyDown={clickOnKeyDown(handleWebappOpen)}
              onClick={handleWebappOpen}
            >
              <div className="w-4 shrink-0" />

              <SvgGlobe size={20} className="stroke-text-02 shrink-0" />

              <div className="flex-1 min-w-0 flex items-center gap-2">
                <Text font="secondary-body" color="text-04" maxLines={1}>
                  {artifact.name}
                </Text>
                <Text font="secondary-body" color="text-02">
                  {t("nextjsApp.label")}
                </Text>
              </div>

              <div className="flex items-center gap-2">
                <Button
                  variant="action"
                  prominence="tertiary"
                  icon={SvgDownloadCloud}
                  onClick={(e) => {
                    e.stopPropagation();
                    handleWebappDownload();
                  }}
                >
                  {t("download.button")}
                </Button>
              </div>
            </div>
          ))}

          {/* Output Files & Folders */}
          {outputEntries.map((entry) => (
            <OutputEntryRow
              key={entry.path}
              entry={entry}
              depth={0}
              onDownload={handleOutputDownload}
              onFileOpen={handleFileOpen}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

interface OutputEntryRowProps {
  entry: OutputEntry;
  depth: number;
  onDownload: (path: string, isDirectory: boolean) => void;
  onFileOpen: (path: string, fileName: string) => void;
}

function OutputEntryRow({
  entry,
  depth,
  onDownload,
  onFileOpen,
}: OutputEntryRowProps) {
  const t = useTranslations("craft.artifactsTab");
  const [expanded, setExpanded] = useState(false);
  const toggleExpand = useCallback(() => {
    setExpanded((prev) => !prev);
  }, []);

  const openEntry = entry.is_directory
    ? toggleExpand
    : () => onFileOpen(entry.path, entry.name);

  const FileIcon = entry.is_directory ? SvgFolder : getFileIcon(entry.name);
  const paddingStart = depth * 20;

  return (
    <>
      {/* The row holds its own buttons, so it stays a div with button
      semantics rather than a <button> wrapping a <button>. */}
      <div
        className="flex items-center gap-3 p-3 hover:bg-background-tint-01 transition-colors cursor-pointer"
        style={{ paddingInlineStart: 12 + paddingStart }}
        role="button"
        tabIndex={0}
        aria-label={
          entry.is_directory
            ? t("toggleItem.ariaLabel", { name: entry.name })
            : t("openItem.ariaLabel", { name: entry.name })
        }
        onKeyDown={clickOnKeyDown(openEntry)}
        onClick={openEntry}
      >
        {entry.is_directory ? (
          expanded ? (
            <SvgChevronDown size={16} className="stroke-text-03 shrink-0" />
          ) : (
            <SvgChevronRight size={16} className="stroke-text-03 shrink-0" />
          )
        ) : (
          <div className="w-4 shrink-0" />
        )}

        <FileIcon size={20} className="stroke-text-02 shrink-0" />

        <div className="flex-1 min-w-0 flex items-center gap-2">
          <Text font="secondary-body" color="text-04" maxLines={1}>
            {entry.name}
          </Text>
          {!entry.is_directory && entry.size !== null ? (
            <Text font="secondary-body" color="text-02">
              {formatBytes(entry.size, 1)}
            </Text>
          ) : null}
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="action"
            prominence="tertiary"
            icon={SvgDownloadCloud}
            onClick={(e) => {
              e.stopPropagation();
              onDownload(entry.path, entry.is_directory);
            }}
          >
            {t("download.button")}
          </Button>
        </div>
      </div>

      {expanded &&
        entry.children.map((child) => (
          <OutputEntryRow
            key={child.path}
            entry={child}
            depth={depth + 1}
            onDownload={onDownload}
            onFileOpen={onFileOpen}
          />
        ))}
    </>
  );
}

interface OutputEntry {
  name: string;
  path: string;
  is_directory: boolean;
  size: number | null;
  children: OutputEntry[];
}

function buildOutputTree(files: Record<string, OutputFile>): OutputEntry[] {
  const root: OutputEntry[] = [];
  const entries = new Map<string, OutputEntry>();
  for (const file of Object.values(files)) {
    const segments = file.path.split("/").slice(1);
    let path = "outputs";
    let children = root;
    segments.forEach((name, index) => {
      path += `/${name}`;
      let entry = entries.get(path);
      if (!entry) {
        const isDirectory = index < segments.length - 1;
        entry = {
          path,
          name,
          is_directory: isDirectory,
          size: isDirectory ? null : file.size,
          children: [],
        };
        entries.set(path, entry);
        children.push(entry);
      }
      children = entry.children;
    });
  }
  const compare = (a: OutputEntry, b: OutputEntry): number =>
    Number(b.is_directory) - Number(a.is_directory) ||
    a.name.localeCompare(b.name);
  root.sort(compare);
  for (const entry of entries.values()) entry.children.sort(compare);
  return root;
}
