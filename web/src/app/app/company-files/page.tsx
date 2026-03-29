"use client";

import { useState, useEffect, useCallback } from "react";
import Text from "@/refresh-components/texts/Text";
import { Card } from "@/refresh-components/cards";
import { Button } from "@opal/components";
import {
  SvgFolder,
  SvgFileText,
  SvgChevronRight,
  SvgArrowLeft,
  SvgExternalLink,
  SvgGlobe,
  SvgUploadCloud,
  SvgArrowUpDown,
} from "@opal/icons";
import { Content } from "@opal/layouts";
import {
  HierarchyNodeSummary,
  DocumentSummary,
  DocumentSortField,
  DocumentSortDirection,
} from "@/lib/hierarchy/interfaces";
import {
  fetchHierarchyNodes,
  fetchHierarchyNodeDocuments,
} from "@/lib/hierarchy/svc";
import { ValidSources } from "@/lib/types";
import { getSourceMetadata } from "@/lib/sources";
import { timeAgo } from "@/lib/time";
import { useUser } from "@/providers/UserProvider";
import { cn } from "@/lib/utils";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";

interface ConnectorStatusEntry {
  source: ValidSources;
  connector_id: number;
  name: string;
}

function getFileExtension(title: string): string {
  const parts = title.split(".");
  if (parts.length > 1) return parts.pop()!.toUpperCase();
  return "FILE";
}

function getFileTypeColor(ext: string): string {
  const colors: Record<string, string> = {
    PDF: "bg-status-error-02 text-status-error-05",
    DOC: "bg-action-link-01 text-action-link-05",
    DOCX: "bg-action-link-01 text-action-link-05",
    XLS: "bg-status-success-01 text-status-success-05",
    XLSX: "bg-status-success-01 text-status-success-05",
    PPT: "bg-status-warning-01 text-status-warning-05",
    PPTX: "bg-status-warning-01 text-status-warning-05",
    TXT: "bg-background-neutral-02 text-text-03",
    CSV: "bg-status-success-01 text-status-success-05",
    MD: "bg-background-neutral-02 text-text-03",
    JSON: "bg-background-neutral-02 text-text-03",
    HTML: "bg-status-warning-01 text-status-warning-05",
  };
  return colors[ext] || "bg-background-neutral-02 text-text-03";
}

interface SortableHeaderProps {
  label: string;
  field: DocumentSortField;
  currentField: DocumentSortField;
  currentDirection: DocumentSortDirection;
  onSort: (field: DocumentSortField) => void;
  className?: string;
}

function SortableHeader({
  label,
  field,
  currentField,
  currentDirection,
  onSort,
  className,
}: SortableHeaderProps) {
  const isActive = currentField === field;
  return (
    <button
      type="button"
      onClick={() => onSort(field)}
      className={cn(
        "flex items-center gap-1 hover:text-text-05 transition-colors",
        isActive ? "text-text-05" : "text-text-03",
        className
      )}
    >
      <Text secondaryBody className={isActive ? "text-text-05" : "text-text-03"}>
        {label}
      </Text>
      <SvgArrowUpDown
        className={cn(
          "w-3 h-3",
          isActive ? "text-text-05" : "text-text-02",
          isActive && currentDirection === "desc" && "rotate-180"
        )}
      />
    </button>
  );
}

export default function CompanyFilesPage() {
  const { isAdmin } = useUser();

  // Fetch available connector sources
  const { data: connectorStatuses } = useSWR<ConnectorStatusEntry[]>(
    "/api/manage/connector-status",
    errorHandlingFetcher
  );

  const availableSources = Array.from(
    new Set((connectorStatuses ?? []).map((c) => c.source))
  );

  const [selectedSource, setSelectedSource] = useState<ValidSources | null>(null);
  const [allNodes, setAllNodes] = useState<HierarchyNodeSummary[]>([]);
  const [path, setPath] = useState<HierarchyNodeSummary[]>([]);
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hierarchyAvailable, setHierarchyAvailable] = useState(true);
  const [sortField, setSortField] = useState<DocumentSortField>("name");
  const [sortDirection, setSortDirection] = useState<DocumentSortDirection>("asc");

  // Auto-select source if only one
  useEffect(() => {
    if (availableSources.length === 1 && !selectedSource) {
      setSelectedSource(availableSources[0]!);
    }
  }, [availableSources, selectedSource]);

  // Load hierarchy nodes when source is selected
  useEffect(() => {
    if (!selectedSource) return;
    setIsLoading(true);
    setError(null);
    fetchHierarchyNodes(selectedSource)
      .then((res) => {
        setAllNodes(res.nodes);
        setPath([]);
        setDocuments([]);
        setHierarchyAvailable(true);
      })
      .catch(() => {
        // Hierarchy API requires OpenSearch — fall back to simple source list view
        setHierarchyAvailable(false);
      })
      .finally(() => setIsLoading(false));
  }, [selectedSource]);

  const currentFolderId = path.length > 0 ? path[path.length - 1]!.id : null;

  const loadDocuments = useCallback(
    async (folderId: number, field: DocumentSortField, direction: DocumentSortDirection) => {
      setIsLoading(true);
      try {
        const res = await fetchHierarchyNodeDocuments({
          parent_hierarchy_node_id: folderId,
          sort_field: field,
          sort_direction: direction,
          folder_position: "on_top",
        });
        setDocuments(res.documents);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load files");
      } finally {
        setIsLoading(false);
      }
    },
    []
  );

  useEffect(() => {
    if (currentFolderId !== null) {
      loadDocuments(currentFolderId, sortField, sortDirection);
    }
  }, [currentFolderId, sortField, sortDirection, loadDocuments]);

  const childFolders = allNodes.filter((n) =>
    path.length === 0 ? n.parent_id === null : n.parent_id === currentFolderId
  );

  const navigateToFolder = (node: HierarchyNodeSummary) => {
    setPath([...path, node]);
    setDocuments([]);
  };

  const navigateToBreadcrumb = (index: number) => {
    setPath(path.slice(0, index + 1));
    setDocuments([]);
  };

  const handleSort = (field: DocumentSortField) => {
    if (field === sortField) {
      setSortDirection((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortField(field);
      setSortDirection("asc");
    }
  };

  // ─── Empty states ───

  if (availableSources.length === 0) {
    return (
      <div className="flex flex-col gap-4 p-6 max-w-4xl mx-auto w-full">
        <Content
          icon={SvgFolder}
          title="Company Files"
          description="Browse documents indexed by the AI to help answer your questions."
          sizePreset="section"
          variant="heading"
        />

        {isAdmin ? (
          // Admin empty state — connect or upload
          <div className="flex gap-4 items-stretch">
            <Card padding={1} className="flex-1">
              <div className="flex flex-col items-center justify-center gap-3 py-8 w-full">
                <SvgGlobe className="w-10 h-10 text-text-02" />
                <Text mainContentEmphasis text03>
                  Connect SharePoint
                </Text>
                <Text secondaryBody text02 className="text-center max-w-xs">
                  Sync documents, pages, and permissions from your SharePoint
                  sites automatically.
                </Text>
                <Button
                  href="/admin/connectors/sharepoint"
                  prominence="secondary"
                  rightIcon={SvgExternalLink}
                >
                  Connect SharePoint
                </Button>
              </div>
            </Card>

            <div className="flex flex-col items-center justify-center gap-2 px-2">
              <div className="w-px flex-1 bg-border-01" />
              <Text secondaryBody text02>or</Text>
              <div className="w-px flex-1 bg-border-01" />
            </div>

            <Card padding={1} className="flex-1">
              <div className="flex flex-col items-center justify-center gap-3 py-8 w-full">
                <SvgUploadCloud className="w-10 h-10 text-text-02" />
                <Text mainContentEmphasis text03>
                  Upload Your Own Files
                </Text>
                <Text secondaryBody text02 className="text-center max-w-xs">
                  Upload PDF, Word, Excel, and other files directly to make them
                  searchable by your team.
                </Text>
                <Button
                  href="/admin/connectors/file"
                  prominence="secondary"
                  rightIcon={SvgExternalLink}
                >
                  Upload Files
                </Button>
              </div>
            </Card>
          </div>
        ) : (
          // Regular user empty state
          <Card padding={1}>
            <div className="flex flex-col items-center gap-3 py-12 w-full">
              <SvgFolder className="w-10 h-10 text-text-02" />
              <Text mainContentEmphasis text03>
                No company files available yet
              </Text>
              <Text secondaryBody text02 className="text-center max-w-sm">
                Your admin hasn't connected any data sources. Once they do,
                you'll be able to browse company documents here that the AI uses
                to answer your questions.
              </Text>
            </div>
          </Card>
        )}
      </div>
    );
  }

  // ─── Source selection (multiple sources) ───

  if (!selectedSource) {
    return (
      <div className="flex flex-col gap-4 p-6 max-w-4xl mx-auto w-full">
        <Content
          icon={SvgFolder}
          title="Company Files"
          description="Browse documents indexed by the AI to help answer your questions."
          sizePreset="section"
          variant="heading"
        />
        <div className="flex flex-col gap-1">
          {availableSources.map((source) => {
            const meta = getSourceMetadata(source);
            return (
              <button
                key={source}
                type="button"
                className="flex items-center justify-between p-3 rounded-12 border border-border-01 bg-background-tint-00 hover:bg-background-tint-01 transition-colors"
                onClick={() => setSelectedSource(source)}
              >
                <div className="flex items-center gap-3">
                  <SvgFolder className="w-5 h-5 text-text-03" />
                  <Text mainUiAction text04>{meta.displayName}</Text>
                </div>
                <SvgChevronRight className="w-4 h-4 text-text-03" />
              </button>
            );
          })}
        </div>
      </div>
    );
  }

  // ─── Fallback: hierarchy API not available ───

  if (!hierarchyAvailable && selectedSource) {
    const meta = getSourceMetadata(selectedSource);
    return (
      <div className="flex flex-col gap-4 p-6 max-w-4xl mx-auto w-full">
        <div className="flex items-center gap-2">
          {availableSources.length > 1 && (
            <Button
              icon={SvgArrowLeft}
              prominence="tertiary"
              size="sm"
              onClick={() => {
                setSelectedSource(null);
                setHierarchyAvailable(true);
              }}
            />
          )}
          <Content
            icon={SvgFolder}
            title="Company Files"
            description="These documents are indexed by the AI to help answer your questions."
            sizePreset="main-content"
            variant="section"
          />
        </div>
        <Card padding={1}>
          <div className="flex flex-col items-center gap-3 py-8 w-full">
            <SvgFolder className="w-10 h-10 text-text-02" />
            <Text mainContentEmphasis text04>
              {meta.displayName}
            </Text>
            <Text secondaryBody text02 className="text-center max-w-sm">
              Your company documents from {meta.displayName} are being indexed
              and used by the AI to answer your questions. Folder browsing will
              be available once indexing is fully configured.
            </Text>
            {isAdmin && (
              <Button
                href="/admin/indexing/status"
                prominence="secondary"
                rightIcon={SvgExternalLink}
              >
                View Indexing Status
              </Button>
            )}
          </div>
        </Card>
      </div>
    );
  }

  // ─── File explorer ───

  return (
    <div className="flex flex-col gap-3 p-6 max-w-5xl mx-auto w-full">
      {/* Header */}
      <div className="flex items-center gap-2">
        {availableSources.length > 1 && (
          <Button
            icon={SvgArrowLeft}
            prominence="tertiary"
            size="sm"
            onClick={() => {
              setSelectedSource(null);
              setPath([]);
              setDocuments([]);
              setAllNodes([]);
            }}
          />
        )}
        <Content
          icon={SvgFolder}
          title="Company Files"
          description="These documents are indexed by the AI to help answer your questions."
          sizePreset="main-content"
          variant="section"
        />
      </div>

      {/* Breadcrumbs */}
      <div className="flex items-center gap-1 flex-wrap px-1">
        <button
          type="button"
          onClick={() => { setPath([]); setDocuments([]); }}
          className="hover:underline"
        >
          <Text mainUiAction className="text-action-link-05">
            {getSourceMetadata(selectedSource).displayName}
          </Text>
        </button>
        {path.map((node, i) => (
          <div key={node.id} className="flex items-center gap-1">
            <SvgChevronRight className="w-3 h-3 text-text-02" />
            {i === path.length - 1 ? (
              <Text mainUiAction text04>{node.title}</Text>
            ) : (
              <button
                type="button"
                onClick={() => navigateToBreadcrumb(i)}
                className="hover:underline"
              >
                <Text mainUiAction className="text-action-link-05">
                  {node.title}
                </Text>
              </button>
            )}
          </div>
        ))}
      </div>

      {/* Error */}
      {error && (
        <div className="p-3 rounded-08 bg-status-error-00 border border-status-error-02">
          <Text secondaryBody className="text-status-error-05">{error}</Text>
        </div>
      )}

      {/* Table */}
      <Card padding={0}>
        {/* Table header */}
        <div className="grid grid-cols-[1fr_140px_100px] gap-2 px-4 py-2.5 border-b border-border-01 bg-background-neutral-01 rounded-t-12">
          <SortableHeader
            label="Name"
            field="name"
            currentField={sortField}
            currentDirection={sortDirection}
            onSort={handleSort}
          />
          <SortableHeader
            label="Modified"
            field="last_updated"
            currentField={sortField}
            currentDirection={sortDirection}
            onSort={handleSort}
          />
          <Text secondaryBody text03>Type</Text>
        </div>

        {/* Loading */}
        {isLoading && (
          <div className="flex items-center justify-center py-12">
            <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-text-01" />
          </div>
        )}

        {/* Rows */}
        {!isLoading && (
          <div className="flex flex-col">
            {/* Folders */}
            {childFolders.map((folder) => (
              <button
                key={folder.id}
                type="button"
                onClick={() => navigateToFolder(folder)}
                className="grid grid-cols-[1fr_140px_100px] gap-2 px-4 py-2.5 border-b border-border-01 hover:bg-background-tint-01 transition-colors text-left"
              >
                <div className="flex items-center gap-3 min-w-0">
                  <SvgFolder className="w-5 h-5 text-text-03 shrink-0" />
                  <Text mainUiAction text04 className="truncate">
                    {folder.title}
                  </Text>
                </div>
                <Text secondaryBody text02>—</Text>
                <Text secondaryBody text02>Folder</Text>
              </button>
            ))}

            {/* Documents */}
            {documents.map((doc) => {
              const ext = getFileExtension(doc.title);
              const colorClass = getFileTypeColor(ext);
              return (
                <div
                  key={doc.id}
                  className="grid grid-cols-[1fr_140px_100px] gap-2 px-4 py-2.5 border-b border-border-01 hover:bg-background-tint-01 transition-colors group"
                >
                  <div className="flex items-center gap-3 min-w-0">
                    <SvgFileText className="w-5 h-5 text-text-03 shrink-0" />
                    <Text mainUiAction text04 className="truncate">
                      {doc.title}
                    </Text>
                    {doc.link && (
                      <a
                        href={doc.link}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="opacity-0 group-hover:opacity-100 transition-opacity shrink-0"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <SvgExternalLink className="w-3.5 h-3.5 text-text-02 hover:text-action-link-05" />
                      </a>
                    )}
                  </div>
                  <Text secondaryBody text02>
                    {doc.last_modified ? timeAgo(doc.last_modified) : "—"}
                  </Text>
                  <span className={cn("px-2 py-0.5 rounded-04 text-xs font-medium w-fit", colorClass)}>
                    {ext}
                  </span>
                </div>
              );
            })}

            {/* Empty state */}
            {childFolders.length === 0 && documents.length === 0 && !isLoading && (
              <div className="flex flex-col items-center gap-2 py-12">
                <SvgFileText className="w-8 h-8 text-text-02" />
                <Text secondaryBody text03>
                  {path.length === 0
                    ? "No files indexed yet. Documents will appear here after the first sync."
                    : "This folder is empty."}
                </Text>
              </div>
            )}
          </div>
        )}
      </Card>
    </div>
  );
}
