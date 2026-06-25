"use client";

import { useCallback, useMemo, useState } from "react";
import * as GeneralLayouts from "@/layouts/general-layouts";
import * as TableLayouts from "@/layouts/table-layouts";
import { Content } from "@opal/layouts";
import { Card } from "@/refresh-components/cards";
import LineItem from "@/refresh-components/buttons/LineItem";
import Text from "@/refresh-components/texts/Text";
import SourceHierarchyBrowser from "@/sections/knowledge/SourceHierarchyBrowser";
import { ValidSources } from "@/lib/types";
import { getSourceMetadata } from "@/lib/sources";
import {
  AttachedDocumentSnapshot,
  HierarchyNodeSnapshot,
} from "@/app/admin/agents/interfaces";

const TUTOR_KNOWLEDGE_SOURCES = [
  ValidSources.Canvas,
  ValidSources.GoogleDrive,
  ValidSources.Web,
] as const;

function buildInitialSourceSelectionCounts(
  initialAttachedDocuments?: AttachedDocumentSnapshot[],
  initialHierarchyNodes?: HierarchyNodeSnapshot[]
) {
  const counts = new Map<ValidSources, number>();

  const increment = (source: ValidSources | null | undefined) => {
    if (!source) return;
    counts.set(source, (counts.get(source) ?? 0) + 1);
  };

  initialAttachedDocuments?.forEach((document) => {
    increment(document.source);
  });
  initialHierarchyNodes?.forEach((node) => {
    increment(node.source);
  });

  return counts;
}

interface TutorKnowledgePaneProps {
  selectedDocumentIds: string[];
  onDocumentIdsChange: (ids: string[]) => void;
  selectedFolderIds: number[];
  onFolderIdsChange: (ids: number[]) => void;
  initialAttachedDocuments?: AttachedDocumentSnapshot[];
  initialHierarchyNodes?: HierarchyNodeSnapshot[];
  // The Canvas course's hierarchy node id, resolved at LTI launch by
  // matching context.title against indexed course nodes. When provided,
  // the browser is scoped to just that course's subtree. When null
  // (Canvas not yet indexed, or duplicate course names), we fall back to
  // showing the whole Canvas hierarchy.
  canvasCourseNodeId: number | null;
}

export default function TutorKnowledgePane({
  selectedDocumentIds,
  onDocumentIdsChange,
  selectedFolderIds,
  onFolderIdsChange,
  initialAttachedDocuments,
  initialHierarchyNodes,
  canvasCourseNodeId,
}: TutorKnowledgePaneProps) {
  const [activeSource, setActiveSource] = useState<ValidSources>(
    ValidSources.Canvas
  );
  const initialSourceSelectionCounts = useMemo(
    () =>
      buildInitialSourceSelectionCounts(
        initialAttachedDocuments,
        initialHierarchyNodes
      ),
    [initialAttachedDocuments, initialHierarchyNodes]
  );
  const [sourceSelectionCountOverrides, setSourceSelectionCountOverrides] =
    useState<Map<ValidSources, number>>(() => new Map());

  const sourceSelectionCounts = useMemo(() => {
    if (selectedDocumentIds.length === 0 && selectedFolderIds.length === 0) {
      return new Map<ValidSources, number>();
    }

    const counts = new Map(initialSourceSelectionCounts);
    sourceSelectionCountOverrides.forEach((count, source) => {
      counts.set(source, count);
    });
    return counts;
  }, [
    initialSourceSelectionCounts,
    sourceSelectionCountOverrides,
    selectedDocumentIds.length,
    selectedFolderIds.length,
  ]);

  const handleToggleDocument = useCallback(
    (documentId: string) => {
      const next = selectedDocumentIds.includes(documentId)
        ? selectedDocumentIds.filter((id) => id !== documentId)
        : [...selectedDocumentIds, documentId];
      onDocumentIdsChange(next);
    },
    [selectedDocumentIds, onDocumentIdsChange]
  );

  const handleToggleFolder = useCallback(
    (folderId: number) => {
      const next = selectedFolderIds.includes(folderId)
        ? selectedFolderIds.filter((id) => id !== folderId)
        : [...selectedFolderIds, folderId];
      onFolderIdsChange(next);
    },
    [selectedFolderIds, onFolderIdsChange]
  );

  const handleDeselectAllDocuments = useCallback(
    () => onDocumentIdsChange([]),
    [onDocumentIdsChange]
  );
  const handleDeselectAllFolders = useCallback(
    () => onFolderIdsChange([]),
    [onFolderIdsChange]
  );

  const handleDeselectSourceItems = useCallback(
    (source: ValidSources, documentIds: string[], folderIds: number[]) => {
      const nextDocumentIds = selectedDocumentIds.filter(
        (id) => !documentIds.includes(id)
      );
      const nextFolderIds = selectedFolderIds.filter(
        (id) => !folderIds.includes(id)
      );
      onDocumentIdsChange(nextDocumentIds);
      onFolderIdsChange(nextFolderIds);
      setSourceSelectionCountOverrides((prev) => {
        const next = new Map(prev);
        next.set(source, 0);
        return next;
      });
    },
    [
      selectedDocumentIds,
      selectedFolderIds,
      onDocumentIdsChange,
      onFolderIdsChange,
    ]
  );

  const handleSelectionCountChange = useCallback(
    (source: ValidSources, count: number) => {
      setSourceSelectionCountOverrides((prev) => {
        if (prev.get(source) === count) {
          return prev;
        }
        const next = new Map(prev);
        next.set(source, count);
        return next;
      });
    },
    []
  );

  return (
    <GeneralLayouts.Section gap={0.5} alignItems="stretch" height="auto">
      <Content
        title="Knowledge"
        description="Choose a source, then select the folders, files, or web pages this tutor should reference."
        sizePreset="main-content"
        variant="section"
      />

      <Card alignItems="stretch">
        <TableLayouts.TwoColumnLayout minHeight={18.75}>
          <TableLayouts.SidebarLayout aria-label="tutor-knowledge-sources">
            {TUTOR_KNOWLEDGE_SOURCES.map((source) => {
              const sourceMetadata = getSourceMetadata(source);
              const isActive = activeSource === source;
              const selectionCount = sourceSelectionCounts.get(source) ?? 0;

              return (
                <LineItem
                  key={source}
                  icon={sourceMetadata.icon}
                  onClick={() => setActiveSource(source)}
                  selected={isActive}
                  emphasized={isActive || selectionCount > 0}
                  aria-label={`tutor-knowledge-source-${source}`}
                  rightChildren={
                    selectionCount > 0 ? (
                      <Text mainUiAction className="text-action-link-05">
                        {selectionCount}
                      </Text>
                    ) : undefined
                  }
                >
                  {sourceMetadata.displayName}
                </LineItem>
              );
            })}
          </TableLayouts.SidebarLayout>

          <TableLayouts.ContentColumn>
            <SourceHierarchyBrowser
              source={activeSource}
              selectedDocumentIds={selectedDocumentIds}
              onToggleDocument={handleToggleDocument}
              onSetDocumentIds={onDocumentIdsChange}
              selectedFolderIds={selectedFolderIds}
              onToggleFolder={handleToggleFolder}
              onSetFolderIds={onFolderIdsChange}
              onDeselectAllDocuments={handleDeselectAllDocuments}
              onDeselectAllFolders={handleDeselectAllFolders}
              onDeselectSourceItems={handleDeselectSourceItems}
              initialAttachedDocuments={initialAttachedDocuments}
              onSelectionCountChange={handleSelectionCountChange}
              hideRootNode={activeSource === ValidSources.Canvas}
              restrictToRootNodeId={
                activeSource === ValidSources.Canvas ? canvasCourseNodeId : null
              }
            />
          </TableLayouts.ContentColumn>
        </TableLayouts.TwoColumnLayout>
      </Card>
    </GeneralLayouts.Section>
  );
}
