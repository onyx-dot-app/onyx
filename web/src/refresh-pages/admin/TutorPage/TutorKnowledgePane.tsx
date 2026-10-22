"use client";

import { useCallback, useMemo, useState } from "react";
import * as GeneralLayouts from "@/layouts/general-layouts";
import * as TableLayouts from "@/layouts/table-layouts";
import { ContentAction, IllustrationContent } from "@opal/layouts";
import { Button } from "@opal/components";
import SvgNoResult from "@opal/illustrations/no-result";
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
  // The Canvas course's indexed hierarchy node id (from the course's
  // connector-status). When provided, the browser is scoped to just that
  // course's subtree. When null the course hasn't been indexed yet, so the
  // Canvas tab shows an empty state rather than every Canvas course.
  canvasCourseNodeId: number | null;
  ltiContextId: string | null;
  knowledgeUrl?: string;
  onSelectionPendingChange?: (pending: boolean) => void;
}

export default function TutorKnowledgePane({
  selectedDocumentIds,
  onDocumentIdsChange,
  selectedFolderIds,
  onFolderIdsChange,
  initialAttachedDocuments,
  initialHierarchyNodes,
  canvasCourseNodeId,
  ltiContextId,
  knowledgeUrl,
  onSelectionPendingChange,
}: TutorKnowledgePaneProps) {
  const [activeSource, setActiveSource] = useState<ValidSources>(
    ValidSources.Canvas
  );
  const [isUpdatingSelection, setIsUpdatingSelection] = useState(false);
  const handleSelectionPendingChange = useCallback(
    (pending: boolean) => {
      setIsUpdatingSelection(pending);
      onSelectionPendingChange?.(pending);
    },
    [onSelectionPendingChange]
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
      <ContentAction
        className="flex-col gap-2 sm:flex-row sm:items-center sm:gap-3"
        title="Knowledge"
        description={
          knowledgeUrl
            ? "Choose a source, then select what this tutor can reference. Add more content on the Knowledge page."
            : "Choose a source, then select the folders, files, or web pages this tutor should reference."
        }
        sizePreset="main-content"
        variant="section"
        paddingVariant="fit"
        rightChildren={
          knowledgeUrl ? (
            <Button
              href={knowledgeUrl}
              target="_self"
              prominence="secondary"
              size="sm"
            >
              Add or manage content
            </Button>
          ) : undefined
        }
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
                  disabled={isUpdatingSelection}
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
            {activeSource === ValidSources.Canvas &&
            canvasCourseNodeId === null ? (
              <IllustrationContent
                illustration={SvgNoResult}
                title="Canvas course not synced yet"
                description="This course's Canvas content hasn't finished indexing. Its pages, files, and assignments will appear here once the sync completes."
              />
            ) : (
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
                onSelectionPendingChange={handleSelectionPendingChange}
                hideRootNode={activeSource === ValidSources.Canvas}
                restrictToRootNodeId={
                  activeSource === ValidSources.Canvas
                    ? canvasCourseNodeId
                    : null
                }
                ltiCourseId={
                  activeSource === ValidSources.GoogleDrive ||
                  activeSource === ValidSources.Web
                    ? ltiContextId
                    : null
                }
              />
            )}
          </TableLayouts.ContentColumn>
        </TableLayouts.TwoColumnLayout>
      </Card>
    </GeneralLayouts.Section>
  );
}
