"use client";

import { memo } from "react";
import { getSourceMetadata } from "@/lib/connectors/utils";
import { useTranslations } from "next-intl";
import * as GeneralLayouts from "@/layouts/general-layouts";
import { Text } from "@opal/components";
import type { ConnectedSource } from "@/lib/hierarchy/types";
import type { ValidSources } from "@/lib/connectors/types/source";
import { LineItemButton } from "@opal/components";
import { SvgFiles, SvgFolder } from "@opal/icons";

interface KnowledgeAddViewProps {
  connectedSources: ConnectedSource[];
  onNavigateToDocumentSets: () => void;
  onNavigateToRecent: () => void;
  onNavigateToSource: (source: ValidSources) => void;
  selectedDocumentSetIds: number[];
  selectedFileIds: string[];
  selectedSources: ValidSources[];
  sourceSelectionCounts: Map<ValidSources, number>;
  vectorDbEnabled: boolean;
}

export const KnowledgeAddView = memo(function KnowledgeAddView({
  connectedSources,
  onNavigateToDocumentSets,
  onNavigateToRecent,
  onNavigateToSource,
  selectedDocumentSetIds,
  selectedFileIds,
  selectedSources,
  sourceSelectionCounts,
  vectorDbEnabled,
}: KnowledgeAddViewProps) {
  const t = useTranslations("knowledge");
  return (
    <GeneralLayouts.Section
      gap={2}
      alignItems="start"
      height="auto"
      aria-label="knowledge-add-view"
    >
      <GeneralLayouts.Section
        flexDirection="row"
        justifyContent="start"
        gap={2}
        height="auto"
        wrap
      >
        {vectorDbEnabled && (
          <LineItemButton
            sizePreset="main-ui"
            variant="section"
            icon={SvgFolder}
            title={t("addView.documentSets.label")}
            onClick={onNavigateToDocumentSets}
            selectVariant={
              selectedDocumentSetIds.length > 0
                ? "select-heavy"
                : "select-light"
            }
            aria-label="knowledge-add-document-sets"
            rightChildren={
              selectedDocumentSetIds.length > 0 ? (
                <Text font="main-ui-action" color="action-selection-05">
                  {String(selectedDocumentSetIds.length)}
                </Text>
              ) : undefined
            }
          />
        )}

        <LineItemButton
          sizePreset="main-ui"
          variant="section"
          icon={SvgFiles}
          title={t("addView.yourFiles.label")}
          description={t("addView.yourFiles.description")}
          onClick={onNavigateToRecent}
          selectVariant={
            selectedFileIds.length > 0 ? "select-heavy" : "select-light"
          }
          aria-label="knowledge-add-files"
          rightChildren={
            selectedFileIds.length > 0 ? (
              <Text font="main-ui-action" color="action-selection-05">
                {String(selectedFileIds.length)}
              </Text>
            ) : undefined
          }
        />
      </GeneralLayouts.Section>

      {vectorDbEnabled && connectedSources.length > 0 && (
        <>
          <Text as="p" font="secondary-body" color="text-03">
            {t("addView.connectedSources.label")}
          </Text>
          {connectedSources.map((connectedSource) => {
            const sourceMetadata = getSourceMetadata(connectedSource.source);
            const isSelected = selectedSources.includes(connectedSource.source);
            const selectionCount =
              sourceSelectionCounts.get(connectedSource.source) ?? 0;
            return (
              <LineItemButton
                key={connectedSource.source}
                sizePreset="main-ui"
                variant="section"
                icon={sourceMetadata.icon}
                title={sourceMetadata.displayName}
                onClick={() => onNavigateToSource(connectedSource.source)}
                selectVariant={
                  isSelected || selectionCount > 0
                    ? "select-heavy"
                    : "select-light"
                }
                aria-label={`knowledge-add-source-${connectedSource.source}`}
                rightChildren={
                  selectionCount > 0 ? (
                    <Text font="main-ui-action" color="action-selection-05">
                      {String(selectionCount)}
                    </Text>
                  ) : undefined
                }
              />
            );
          })}
        </>
      )}
    </GeneralLayouts.Section>
  );
});
