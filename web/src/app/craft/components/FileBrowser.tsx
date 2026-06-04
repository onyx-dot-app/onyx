"use client";

import { useState, useCallback, useEffect } from "react";
import { Button, Text } from "@opal/components";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/refresh-components/Collapsible";
import {
  SvgFolder,
  SvgFolderOpen,
  SvgFileSmall,
  SvgChevronRight,
  SvgChevronDown,
  SvgDownloadCloud,
  SvgEye,
  SvgHardDrive,
  SvgLoader,
} from "@opal/icons";
import {
  listDirectory,
  getArtifactUrl,
  FileSystemEntry,
} from "@/lib/build/client";
import FilePreviewModal from "@/app/craft/components/FilePreviewModal";

interface FileBrowserProps {
  sessionId: string;
}

interface DirectoryNodeProps {
  entry: FileSystemEntry;
  sessionId: string;
  depth: number;
  onPreview: (entry: FileSystemEntry) => void;
}

function DirectoryNode({
  entry,
  sessionId,
  depth,
  onPreview,
}: DirectoryNodeProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [children, setChildren] = useState<FileSystemEntry[] | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadChildren = useCallback(async () => {
    if (children !== null) return;

    setIsLoading(true);
    setError(null);
    try {
      const listing = await listDirectory(sessionId, entry.path);
      setChildren(listing.entries);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load directory");
    } finally {
      setIsLoading(false);
    }
  }, [sessionId, entry.path, children]);

  const handleToggle = async (open: boolean) => {
    setIsOpen(open);
    if (open) {
      await loadChildren();
    }
  };

  const paddingLeft = depth * 1.25;

  return (
    <Collapsible open={isOpen} onOpenChange={handleToggle}>
      <CollapsibleTrigger asChild>
        <button
          className="w-full flex flex-row items-center gap-2 p-2 hover:bg-background-neutral-01 rounded-08 transition-colors"
          style={{ paddingLeft: `${paddingLeft}rem` }}
        >
          {isLoading ? (
            <SvgLoader className="size-4 stroke-text-03 animate-spin" />
          ) : isOpen ? (
            <SvgChevronDown className="size-4 stroke-text-03" />
          ) : (
            <SvgChevronRight className="size-4 stroke-text-03" />
          )}
          {isOpen ? (
            <SvgFolderOpen className="size-4 stroke-text-03" />
          ) : (
            <SvgFolder className="size-4 stroke-text-03" />
          )}
          <Text font="main-content-mono" color="text-04" maxLines={1}>
            {entry.name}
          </Text>
        </button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        {error && (
          <div style={{ paddingLeft: `${paddingLeft + 1.25}rem` }}>
            <Text font="secondary-body" color="status-error-01">
              {error}
            </Text>
          </div>
        )}
        {children?.map((child) =>
          child.is_directory ? (
            <DirectoryNode
              key={child.path}
              entry={child}
              sessionId={sessionId}
              depth={depth + 1}
              onPreview={onPreview}
            />
          ) : (
            <FileNode
              key={child.path}
              entry={child}
              sessionId={sessionId}
              depth={depth + 1}
              onPreview={onPreview}
            />
          )
        )}
      </CollapsibleContent>
    </Collapsible>
  );
}

interface FileNodeProps {
  entry: FileSystemEntry;
  sessionId: string;
  depth: number;
  onPreview: (entry: FileSystemEntry) => void;
}

function FileNode({ entry, sessionId, depth, onPreview }: FileNodeProps) {
  const paddingLeft = depth * 1.25;
  const downloadUrl = getArtifactUrl(sessionId, entry.path);

  const canPreview =
    entry.mime_type?.startsWith("text/") ||
    entry.mime_type?.startsWith("image/") ||
    entry.mime_type === "application/json" ||
    entry.name.endsWith(".md") ||
    entry.name.endsWith(".txt") ||
    entry.name.endsWith(".json") ||
    entry.name.endsWith(".js") ||
    entry.name.endsWith(".ts") ||
    entry.name.endsWith(".tsx") ||
    entry.name.endsWith(".jsx") ||
    entry.name.endsWith(".css") ||
    entry.name.endsWith(".html") ||
    entry.name.endsWith(".py") ||
    entry.name.endsWith(".yaml") ||
    entry.name.endsWith(".yml");

  const formatSize = (bytes: number | null) => {
    if (bytes === null) return "";
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  return (
    <div
      className="w-full flex flex-row items-center gap-2 p-2 hover:bg-background-neutral-01 rounded-08 transition-colors group"
      style={{ paddingLeft: `${paddingLeft + 1.25}rem` }}
    >
      <SvgFileSmall className="size-4 stroke-text-03 shrink-0" />
      <div className="flex-1 min-w-0">
        <Text font="main-content-mono" color="text-04" maxLines={1}>
          {entry.name}
        </Text>
      </div>
      {entry.size !== null && (
        <div className="shrink-0">
          <Text font="secondary-body" color="text-03">
            {formatSize(entry.size)}
          </Text>
        </div>
      )}
      <div className="flex flex-row gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
        {canPreview && (
          <Button
            variant="action"
            prominence="tertiary"
            icon={SvgEye}
            onClick={(e) => {
              e.stopPropagation();
              onPreview(entry);
            }}
          >
            Preview
          </Button>
        )}
        <a
          href={downloadUrl}
          download={entry.name}
          onClick={(e) => e.stopPropagation()}
        >
          <Button
            variant="action"
            prominence="tertiary"
            icon={SvgDownloadCloud}
          >
            Download
          </Button>
        </a>
      </div>
    </div>
  );
}

export default function FileBrowser({ sessionId }: FileBrowserProps) {
  const [rootEntries, setRootEntries] = useState<FileSystemEntry[] | null>(
    null
  );
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [previewFile, setPreviewFile] = useState<FileSystemEntry | null>(null);
  const [isOpen, setIsOpen] = useState(true);

  const loadRoot = useCallback(async () => {
    if (rootEntries !== null) return;

    setIsLoading(true);
    setError(null);
    try {
      const listing = await listDirectory(sessionId);
      setRootEntries(listing.entries);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load file system"
      );
    } finally {
      setIsLoading(false);
    }
  }, [sessionId, rootEntries]);

  const handleToggleRoot = async (open: boolean) => {
    setIsOpen(open);
    if (open) {
      await loadRoot();
    }
  };

  const handlePreview = (entry: FileSystemEntry) => {
    setPreviewFile(entry);
  };

  const handleClosePreview = () => {
    setPreviewFile(null);
  };

  // Auto-load on mount
  useEffect(() => {
    loadRoot();
  }, []);

  return (
    <>
      <div className="border border-border-01 rounded-08 overflow-hidden">
        <Collapsible open={isOpen} onOpenChange={handleToggleRoot}>
          <CollapsibleTrigger asChild>
            <button className="w-full flex flex-row items-center gap-2 p-2 bg-background-neutral-01 hover:bg-background-neutral-02 transition-colors">
              {isLoading ? (
                <SvgLoader className="size-4 stroke-text-03 animate-spin" />
              ) : isOpen ? (
                <SvgChevronDown className="size-4 stroke-text-03" />
              ) : (
                <SvgChevronRight className="size-4 stroke-text-03" />
              )}
              <SvgHardDrive className="size-4 stroke-text-03" />
              <Text font="main-ui-action" color="text-03">
                Workspace Files
              </Text>
            </button>
          </CollapsibleTrigger>
          <CollapsibleContent>
            <div className="p-1 max-h-[50vh] overflow-auto">
              {error && (
                <div className="p-2">
                  <Text font="secondary-body" color="status-error-01">
                    {error}
                  </Text>
                </div>
              )}
              {rootEntries?.length === 0 && (
                <div className="p-2 text-center">
                  <Text font="secondary-body" color="text-03">
                    No files yet
                  </Text>
                </div>
              )}
              {rootEntries?.map((entry) =>
                entry.is_directory ? (
                  <DirectoryNode
                    key={entry.path}
                    entry={entry}
                    sessionId={sessionId}
                    depth={0}
                    onPreview={handlePreview}
                  />
                ) : (
                  <FileNode
                    key={entry.path}
                    entry={entry}
                    sessionId={sessionId}
                    depth={0}
                    onPreview={handlePreview}
                  />
                )
              )}
            </div>
          </CollapsibleContent>
        </Collapsible>
      </div>

      {previewFile && (
        <FilePreviewModal
          sessionId={sessionId}
          entry={previewFile}
          onClose={handleClosePreview}
        />
      )}
    </>
  );
}
