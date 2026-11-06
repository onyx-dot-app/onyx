"use client";

import { Section } from "@opal/layouts";
import { memo } from "react";
import { getSourceMetadata } from "@/lib/connectors/utils";
import { useFormatter, useTranslations } from "next-intl";
import type { ConnectedSource } from "@/lib/hierarchy/types";
import type { ValidSources } from "@/lib/connectors/types/source";
import { Text, LineItemButton } from "@opal/components";
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
  const format = useFormatter();
  return (
    <Section
      gap={2}
      alignItems="start"
      height="auto"
      aria-label="knowledge-add-view"
    >
      <Section
        flexDirection="row"
        justifyContent="start"
        gap={2}
        height="auto"
        wrap
      >
        {vectorDbEnabled && (
          <LineItemButton
            font="main-ui-action"
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
                  {format.number(selectedDocumentSetIds.length)}
                </Text>
              ) : undefined
            }
          />
        )}

        <LineItemButton
          font="main-ui-action"
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
                {format.number(selectedFileIds.length)}
              </Text>
            ) : undefined
          }
        />
      </Section>

      {vectorDbEnabled && connectedSources.length > 0 && (
        <>
          <Text as="p" color="text-03" font="secondary-body">
            {t("addView.connectedSources.label")}
          </Text>
          {connectedSources.map((connectedSource) => {
            const sourceMetadata = getSourceMetadata(connectedSource.source);
            const isSelected = selectedSources.includes(connectedSource.source);
            const selectionCount =
              sourceSelectionCounts.get(connectedSource.source) ?? 0;
            return (
              <LineItemButton
                font="main-ui-action"
                key={connectedSource.source}
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
                      {format.number(selectionCount)}
                    </Text>
                  ) : undefined
                }
              />
            );
          })}
        </>
      )}
    </Section>
  );
});
