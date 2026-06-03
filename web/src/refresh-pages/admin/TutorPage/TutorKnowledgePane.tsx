"use client";

import { useCallback } from "react";
import * as GeneralLayouts from "@/layouts/general-layouts";
import { Content } from "@opal/layouts";
import { Card } from "@/refresh-components/cards";
import SourceHierarchyBrowser from "@/sections/knowledge/SourceHierarchyBrowser";
import { ValidSources } from "@/lib/types";
import { AttachedDocumentSnapshot } from "@/app/admin/agents/interfaces";
import TutorInstructorWebsites from "@/refresh-pages/tutor/TutorInstructorWebsites";

// The Virtual Tutor knowledge pane is intentionally narrower than the generic
// AgentKnowledgePane: a tutor's knowledge is its Canvas course plus any public
// websites the instructor adds for that course. We render the Canvas hierarchy
// browser inline (no source picker, no document sets, no on/off toggle —
// Canvas is always enabled) and, when a course is bound, the per-course website
// manager below it.

interface TutorKnowledgePaneProps {
  selectedDocumentIds: string[];
  onDocumentIdsChange: (ids: string[]) => void;
  selectedFolderIds: number[];
  onFolderIdsChange: (ids: number[]) => void;
  initialAttachedDocuments?: AttachedDocumentSnapshot[];
  // The Canvas course's hierarchy node id, resolved at LTI launch by
  // matching context.title against indexed course nodes. When provided,
  // the browser is scoped to just that course's subtree. When null
  // (Canvas not yet indexed, or duplicate course names), we fall back to
  // showing the whole Canvas hierarchy.
  canvasCourseNodeId: number | null;
  // The LTI `context.id` this tutor is bound to. Required to manage the
  // course's website connectors; when null (no course bound) the website
  // manager is hidden.
  courseId: string | null;
}

export default function TutorKnowledgePane({
  selectedDocumentIds,
  onDocumentIdsChange,
  selectedFolderIds,
  onFolderIdsChange,
  initialAttachedDocuments,
  canvasCourseNodeId,
  courseId,
}: TutorKnowledgePaneProps) {
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

  return (
    <GeneralLayouts.Section gap={0.5} alignItems="stretch" height="auto">
      <Content
        title="Knowledge"
        description="Pick the Canvas folders and documents this tutor should reference when answering students."
        sizePreset="main-content"
        variant="section"
      />

      <Card>
        <GeneralLayouts.Section alignItems="stretch" height="auto">
          <SourceHierarchyBrowser
            source={ValidSources.Canvas}
            selectedDocumentIds={selectedDocumentIds}
            onToggleDocument={handleToggleDocument}
            onSetDocumentIds={onDocumentIdsChange}
            selectedFolderIds={selectedFolderIds}
            onToggleFolder={handleToggleFolder}
            onSetFolderIds={onFolderIdsChange}
            onDeselectAllDocuments={handleDeselectAllDocuments}
            onDeselectAllFolders={handleDeselectAllFolders}
            initialAttachedDocuments={initialAttachedDocuments}
            hideRootNode
            restrictToRootNodeId={canvasCourseNodeId}
          />
        </GeneralLayouts.Section>
      </Card>

      {courseId && <TutorInstructorWebsites courseId={courseId} />}
    </GeneralLayouts.Section>
  );
}
