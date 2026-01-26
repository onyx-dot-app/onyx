import React from "react";
import { SvgSearch, SvgGlobe, SvgSearchMenu } from "@opal/icons";
import { SearchToolPacket } from "@/app/app/services/streamingModels";
import {
  MessageRenderer,
  RenderType,
} from "@/app/app/message/messageComponents/interfaces";
import { BlinkingDot } from "@/app/app/message/BlinkingDot";
import { OnyxDocument } from "@/lib/search/interfaces";
import { ValidSources } from "@/lib/types";
import { SearchChipList, SourceInfo } from "./SearchChipList";
import {
  constructCurrentSearchState,
  INITIAL_QUERIES_TO_SHOW,
  QUERIES_PER_EXPANSION,
  INITIAL_RESULTS_TO_SHOW,
  RESULTS_PER_EXPANSION,
  getMetadataTags,
} from "./searchStateUtils";
import Text from "@/refresh-components/texts/Text";

const queryToSourceInfo = (query: string, index: number): SourceInfo => ({
  id: `query-${index}`,
  title: query,
  sourceType: ValidSources.Web,
  icon: SvgSearch,
});

const resultToSourceInfo = (doc: OnyxDocument): SourceInfo => ({
  id: doc.document_id,
  title: doc.semantic_identifier || "",
  sourceType: doc.source_type,
  sourceUrl: doc.link,
  description: doc.blurb,
  metadata: {
    date: doc.updated_at || undefined,
    tags: getMetadataTags(doc.metadata),
  },
});

export const SearchToolRenderer: MessageRenderer<SearchToolPacket, {}> = ({
  packets,
  onComplete,
  animate,
  stopPacketSeen,
  renderType,
  children,
}) => {
  const searchState = constructCurrentSearchState(packets);
  const { queries, results, isSearching, isComplete, isInternetSearch } =
    searchState;

  const isCompact = renderType === RenderType.COMPACT;

  const icon = isInternetSearch ? SvgGlobe : SvgSearchMenu;
  const queriesHeader = isInternetSearch
    ? "Searching the web for:"
    : "Searching internal documents for:";

  if (queries.length === 0) {
    return children({
      icon,
      status: null,
      content: <div />,
      supportsCompact: true,
    });
  }

  return children({
    icon,
    status: queriesHeader,
    supportsCompact: true,
    content: (
      <div className="flex flex-col">
        {!isCompact && (
          <SearchChipList
            items={queries}
            initialCount={INITIAL_QUERIES_TO_SHOW}
            expansionCount={QUERIES_PER_EXPANSION}
            getKey={(_, index) => index}
            toSourceInfo={queryToSourceInfo}
            emptyState={<BlinkingDot />}
            showDetailsCard={false}
          />
        )}

        {(results.length > 0 || queries.length > 0) && (
          <>
            {!isCompact && (
              <Text as="p" mainUiMuted text03>
                Reading results:
              </Text>
            )}
            <SearchChipList
              items={results}
              initialCount={INITIAL_RESULTS_TO_SHOW}
              expansionCount={RESULTS_PER_EXPANSION}
              getKey={(doc: OnyxDocument) => doc.document_id}
              toSourceInfo={(doc: OnyxDocument) => resultToSourceInfo(doc)}
              onClick={(doc: OnyxDocument) => {
                if (doc.link) {
                  window.open(doc.link, "_blank");
                }
              }}
              emptyState={<BlinkingDot />}
            />
          </>
        )}
      </div>
    ),
  });
};
