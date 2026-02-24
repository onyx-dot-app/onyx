import { SvgSearch, SvgSearchMenu } from "@opal/icons";
import { SearchToolPacket } from "@/app/app/services/streamingModels";
import {
  MessageRenderer,
  RenderType,
} from "@/app/app/message/messageComponents/interfaces";
import { BlinkingBar } from "@/app/app/message/BlinkingBar";
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

/**
 * InternalSearchToolRenderer - Renders internal document search tool execution steps
 *
 * RenderType modes:
 * - FULL: Shows 1 combined timeline step (queries + results together).
 *         Used when step is expanded in timeline.
 * - COMPACT: Shows only results (no queries). Header passed as `status` prop.
 *            Used when step is collapsed in timeline, still wrapped in StepContainer.
 * - HIGHLIGHT: Shows only results with header embedded directly in content.
 *              No StepContainer wrapper. Used for parallel streaming preview.
 * - INLINE: Phase-based (queries -> results) for collapsed streaming view.
 */
export const InternalSearchToolRenderer: MessageRenderer<
  SearchToolPacket,
  {}
> = ({
  packets,
  onComplete,
  animate,
  stopPacketSeen,
  renderType,
  children,
}) => {
  const searchState = constructCurrentSearchState(packets);
  const { queries, results } = searchState;

  const isCompact = renderType === RenderType.COMPACT;
  const isHighlight = renderType === RenderType.HIGHLIGHT;
  const isInline = renderType === RenderType.INLINE;

  const hasResults = results.length > 0;

  const queriesHeader = "Searching internal documents";

  if (queries.length === 0) {
    return children([
      {
        icon: SvgSearchMenu,
        status: null,
        content: <></>,
        supportsCollapsible: true,
        timelineLayout: "timeline",
      },
    ]);
  }

  // HIGHLIGHT mode: header embedded in content, no StepContainer
  if (isHighlight) {
    return children([
      {
        icon: null,
        status: null,
        supportsCollapsible: true,
        timelineLayout: "content",
        content: (
          <div className="flex flex-col">
            <Text as="p" text04 mainUiMuted className="mb-1">
              {queriesHeader}
            </Text>
            <SearchChipList
              items={results}
              initialCount={INITIAL_RESULTS_TO_SHOW}
              expansionCount={RESULTS_PER_EXPANSION}
              getKey={(doc: OnyxDocument, index: number) =>
                doc.document_id ?? `result-${index}`
              }
              toSourceInfo={(doc: OnyxDocument) => resultToSourceInfo(doc)}
              onClick={(doc: OnyxDocument) => {
                if (doc.link) {
                  window.open(doc.link, "_blank", "noopener,noreferrer");
                }
              }}
              emptyState={!stopPacketSeen ? <BlinkingBar /> : undefined}
            />
          </div>
        ),
      },
    ]);
  }

  // INLINE mode: dynamic phase-based content for collapsed streaming view
  if (isInline) {
    // Querying phase: show queries
    if (!hasResults) {
      return children([
        {
          icon: null,
          status: queriesHeader,
          supportsCollapsible: true,
          timelineLayout: "content",
          content: (
            <SearchChipList
              items={queries}
              initialCount={INITIAL_QUERIES_TO_SHOW}
              expansionCount={QUERIES_PER_EXPANSION}
              getKey={(_, index) => index}
              toSourceInfo={queryToSourceInfo}
              emptyState={!stopPacketSeen ? <BlinkingBar /> : undefined}
              showDetailsCard={false}
              isQuery={true}
            />
          ),
        },
      ]);
    }

    // Reading phase: show results
    return children([
      {
        icon: null,
        status: "Reading",
        supportsCollapsible: true,
        timelineLayout: "content",
        content: (
          <SearchChipList
            items={results}
            initialCount={INITIAL_RESULTS_TO_SHOW}
            expansionCount={RESULTS_PER_EXPANSION}
            getKey={(doc: OnyxDocument, index: number) =>
              doc.document_id ?? `result-${index}`
            }
            toSourceInfo={(doc: OnyxDocument) => resultToSourceInfo(doc)}
            onClick={(doc: OnyxDocument) => {
              if (doc.link) {
                window.open(doc.link, "_blank", "noopener,noreferrer");
              }
            }}
            emptyState={!stopPacketSeen ? <BlinkingBar /> : undefined}
          />
        ),
      },
    ]);
  }

  // FULL and COMPACT modes: single combined step (queries + results together)
  return children([
    {
      icon: SvgSearchMenu,
      status: queriesHeader,
      supportsCollapsible: true,
      timelineLayout: "timeline",
      content: (
        <div className="flex flex-col">
          {!isCompact && (
            <SearchChipList
              items={queries}
              initialCount={INITIAL_QUERIES_TO_SHOW}
              expansionCount={QUERIES_PER_EXPANSION}
              getKey={(_, index) => index}
              toSourceInfo={queryToSourceInfo}
              emptyState={!stopPacketSeen ? <BlinkingBar /> : undefined}
              showDetailsCard={false}
              isQuery={true}
            />
          )}

          {(results.length > 0 || queries.length > 0) && (
            <>
              {!isCompact && (
                <Text as="p" mainUiMuted text04>
                  Reading
                </Text>
              )}
              <SearchChipList
                items={results}
                initialCount={INITIAL_RESULTS_TO_SHOW}
                expansionCount={RESULTS_PER_EXPANSION}
                getKey={(doc: OnyxDocument, index: number) =>
                  doc.document_id ?? `result-${index}`
                }
                toSourceInfo={(doc: OnyxDocument) => resultToSourceInfo(doc)}
                onClick={(doc: OnyxDocument) => {
                  if (doc.link) {
                    window.open(doc.link, "_blank", "noopener,noreferrer");
                  }
                }}
                emptyState={!stopPacketSeen ? <BlinkingBar /> : undefined}
              />
            </>
          )}
        </div>
      ),
    },
  ]);
};
