"use client";

import { memo } from "react";
import { useTranslations } from "next-intl";
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
  const t = useTranslations("knowledge");

  if (!hasAnyKnowledge) {
    return (
      <GeneralLayouts.Section
        flexDirection="row"
        justifyContent="between"
        alignItems="center"
        height="auto"
      >
        <Text text03 secondaryBody>
          {t("mainContent.empty.description")}
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
        {t("mainContent.selectedCount.label", { count: totalSelected })}
      </Text>
      <Button
        prominence="internal"
        icon={SvgArrowUpRight}
        onClick={onViewEdit}
        aria-label="knowledge-view-edit"
      >
        {t("mainContent.viewEdit.label")}
      </Button>
    </GeneralLayouts.Section>
  );
});
