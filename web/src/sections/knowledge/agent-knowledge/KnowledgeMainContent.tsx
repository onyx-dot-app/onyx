"use client";

import { memo } from "react";
import * as GeneralLayouts from "@/layouts/general-layouts";
import Text from "@/refresh-components/texts/Text";
import type { ValidSources } from "@/lib/types";
import { Button } from "@opal/components";
import { SvgArrowUpRight, SvgPlusCircle } from "@opal/icons";

interface KnowledgeMainContentProps {
  hasAnyKnowledge: boolean;
  selectedDocumentSetIds: number[];
  selectedDocumentIds: string[];
  selectedFolderIds: number[];
  selectedFileIds: string[];
  selectedSources: ValidSources[];
  onAddKnowledge: () => void;
  onViewEdit: () => void;
}

export const KnowledgeMainContent = memo(function KnowledgeMainContent({
  hasAnyKnowledge,
  selectedDocumentSetIds,
  selectedDocumentIds,
  selectedFolderIds,
  selectedFileIds,
  selectedSources,
  onAddKnowledge,
  onViewEdit,
}: KnowledgeMainContentProps) {
  if (!hasAnyKnowledge) {
    return (
      <GeneralLayouts.Section
        flexDirection="row"
        justifyContent="between"
        alignItems="center"
        height="auto"
      >
        <Text text03 secondaryBody>
          Add documents or connected sources to use for this agent.
        </Text>
        <Button
          icon={SvgPlusCircle}
          onClick={onAddKnowledge}
          prominence="tertiary"
          aria-label="knowledge-add-button"
        />
      </GeneralLayouts.Section>
    );
  }

  const totalSelected =
    selectedDocumentSetIds.length +
    selectedDocumentIds.length +
    selectedFolderIds.length +
    selectedFileIds.length +
    selectedSources.length;

  return (
    <GeneralLayouts.Section
      flexDirection="row"
      justifyContent="between"
      alignItems="center"
      height="auto"
    >
      <Text as="p" text03 secondaryBody>
        {totalSelected} knowledge source{totalSelected !== 1 ? "s" : ""}{" "}
        selected
      </Text>
      <Button
        prominence="internal"
        icon={SvgArrowUpRight}
        onClick={onViewEdit}
        aria-label="knowledge-view-edit"
      >
        View / Edit
      </Button>
    </GeneralLayouts.Section>
  );
});
