"use client";

import React, { useMemo, useState } from "react";
import * as GeneralLayouts from "@/layouts/general-layouts";
import * as TableLayouts from "@/layouts/table-layouts";
import Text from "@/refresh-components/texts/Text";
import { getSourceMetadata } from "@/lib/sources";
import type { AgentAttachedDocument } from "@/lib/agents/types";
import type { ProjectFile } from "@/lib/projects/types";
import type {
  CCPairSummary,
  DocumentSetSummary,
  ValidSources,
} from "@/lib/types";
import SourceHierarchyBrowser from "@/sections/knowledge/SourceHierarchyBrowser";
import { Button } from "@opal/components";
import { Content } from "@opal/layouts";
import { timeAgo } from "@opal/time";
import { SvgFiles, SvgFolder, SvgPlusCircle } from "@opal/icons";

import {
  KnowledgeTable,
  type KnowledgeTableColumn,
} from "@/sections/knowledge/agent-knowledge/KnowledgeTable";

interface DocumentSetsTableContentProps {
  documentSets: DocumentSetSummary[];
  selectedDocumentSetIds: number[];
  onDocumentSetToggle: (documentSetId: number) => void;
}

export function DocumentSetsTableContent({
  documentSets,
  selectedDocumentSetIds,
  onDocumentSetToggle,
}: DocumentSetsTableContentProps) {
  const [searchValue, setSearchValue] = useState("");

  const filteredDocumentSets = useMemo(() => {
    if (!searchValue) return documentSets;
    const lower = searchValue.toLowerCase();
    return documentSets.filter((ds) => ds.name.toLowerCase().includes(lower));
  }, [documentSets, searchValue]);

  const columns: KnowledgeTableColumn<DocumentSetSummary>[] = [
    {
      key: "name",
      header: "Name",
      sortable: true,
      render: (ds) => (
        <Content
          icon={SvgFolder}
          title={ds.name}
          sizePreset="main-ui"
          variant="section"
        />
      ),
    },
    {
      key: "sources",
      header: "Sources",
      width: 8,
      render: (ds) => (
        <TableLayouts.SourceIconsRow>
          {ds.cc_pair_summaries
            ?.slice(0, 4)
            .map((summary: CCPairSummary, idx: number) => {
              const sourceMetadata = getSourceMetadata(summary.source);
              return <sourceMetadata.icon key={idx} size={16} />;
            })}
          {(ds.cc_pair_summaries?.length ?? 0) > 4 && (
            <Text text03 secondaryBody>
              +{(ds.cc_pair_summaries?.length ?? 0) - 4}
            </Text>
          )}
        </TableLayouts.SourceIconsRow>
      ),
    },
  ];

  return (
    <KnowledgeTable
      items={filteredDocumentSets}
      columns={columns}
      getItemId={(ds) => ds.id}
      selectedIds={selectedDocumentSetIds}
      onToggleItem={(id) => onDocumentSetToggle(id as number)}
      searchValue={searchValue}
      onSearchChange={setSearchValue}
      searchPlaceholder="Filter document sets..."
      emptyMessage="No document sets available."
      ariaLabelPrefix="document-set-row"
    />
  );
}

interface SourcesTableContentProps {
  source: ValidSources;
  selectedDocumentIds: string[];
  onToggleDocument: (documentId: string) => void;
  onSetDocumentIds: (ids: string[]) => void;
  selectedFolderIds: number[];
  onToggleFolder: (folderId: number) => void;
  onSetFolderIds: (ids: number[]) => void;
  onDeselectAllDocuments: () => void;
  onDeselectAllFolders: () => void;
  initialAttachedDocuments?: AgentAttachedDocument[];
  onSelectionCountChange?: (source: ValidSources, count: number) => void;
  initialNodeId?: number;
}

export function SourcesTableContent({
  source,
  selectedDocumentIds,
  onToggleDocument,
  onSetDocumentIds,
  selectedFolderIds,
  onToggleFolder,
  onSetFolderIds,
  onDeselectAllDocuments,
  onDeselectAllFolders,
  initialAttachedDocuments,
  onSelectionCountChange,
  initialNodeId,
}: SourcesTableContentProps) {
  return (
    <GeneralLayouts.Section gap={0.5} alignItems="stretch">
      <SourceHierarchyBrowser
        source={source}
        selectedDocumentIds={selectedDocumentIds}
        onToggleDocument={onToggleDocument}
        onSetDocumentIds={onSetDocumentIds}
        selectedFolderIds={selectedFolderIds}
        onToggleFolder={onToggleFolder}
        onSetFolderIds={onSetFolderIds}
        initialAttachedDocuments={initialAttachedDocuments}
        onDeselectAllDocuments={onDeselectAllDocuments}
        onDeselectAllFolders={onDeselectAllFolders}
        onSelectionCountChange={onSelectionCountChange}
        initialNodeId={initialNodeId}
      />
    </GeneralLayouts.Section>
  );
}

interface RecentFilesTableContentProps {
  allRecentFiles: ProjectFile[];
  selectedFileIds: string[];
  onToggleFile: (fileId: string) => void;
  onUploadChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  hasProcessingFiles: boolean;
}

export function RecentFilesTableContent({
  allRecentFiles,
  selectedFileIds,
  onToggleFile,
  onUploadChange,
  hasProcessingFiles,
}: RecentFilesTableContentProps) {
  const [searchValue, setSearchValue] = useState("");

  const filteredFiles = useMemo(() => {
    if (!searchValue) return allRecentFiles;
    const lower = searchValue.toLowerCase();
    return allRecentFiles.filter((f) => f.name.toLowerCase().includes(lower));
  }, [allRecentFiles, searchValue]);

  const columns: KnowledgeTableColumn<ProjectFile>[] = [
    {
      key: "name",
      header: "Name",
      sortable: true,
      render: (file) => (
        <Content
          icon={SvgFiles}
          title={file.name}
          sizePreset="main-ui"
          variant="section"
        />
      ),
    },
    {
      key: "lastUpdated",
      header: "Last Updated",
      sortable: true,
      width: 8,
      render: (file) => (
        <Text text03 secondaryBody>
          {timeAgo(file.last_accessed_at || file.created_at)}
        </Text>
      ),
    },
  ];

  const fileInputRef = React.useRef<HTMLInputElement>(null);

  return (
    <GeneralLayouts.Section gap={0.5} alignItems="stretch">
      <TableLayouts.HiddenInput
        inputRef={fileInputRef}
        type="file"
        multiple
        onChange={onUploadChange}
      />

      <KnowledgeTable
        items={filteredFiles}
        columns={columns}
        getItemId={(file) => file.id}
        selectedIds={selectedFileIds}
        onToggleItem={(id) => onToggleFile(id as string)}
        searchValue={searchValue}
        onSearchChange={setSearchValue}
        searchPlaceholder="Filter files..."
        ariaLabelPrefix="user-file-row"
        headerActions={
          <Button
            prominence="internal"
            icon={SvgPlusCircle}
            onClick={() => fileInputRef.current?.click()}
          >
            Add File
          </Button>
        }
        emptyMessage="No files available. Upload files to get started."
      />

      {hasProcessingFiles && (
        <GeneralLayouts.Section height="auto" alignItems="start">
          <Text as="p" text03 secondaryBody>
            Onyx is still processing your uploaded files. You can create the
            agent now, but it will not have access to all files until processing
            completes.
          </Text>
        </GeneralLayouts.Section>
      )}
    </GeneralLayouts.Section>
  );
}
