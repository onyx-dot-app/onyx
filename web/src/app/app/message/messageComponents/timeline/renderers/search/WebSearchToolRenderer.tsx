import React from "react";
import { SvgSearch, SvgGlobe } from "@opal/icons";
import { SearchToolPacket } from "@/app/app/services/streamingModels";
import {
  MessageRenderer,
  RenderType,
} from "@/app/app/message/messageComponents/interfaces";
import { BlinkingBar } from "@/app/app/message/BlinkingBar";
import { ValidSources } from "@/lib/types";
import { SearchChipList, SourceInfo } from "./SearchChipList";
import {
  constructCurrentSearchState,
  INITIAL_QUERIES_TO_SHOW,
  QUERIES_PER_EXPANSION,
  SearchDebugState,
} from "./searchStateUtils";
import Text from "@/refresh-components/texts/Text";

const queryToSourceInfo = (query: string, index: number): SourceInfo => ({
  id: `query-${index}`,
  title: query,
  sourceType: ValidSources.Web,
  icon: SvgSearch,
});

function formatDebugSummary(debug: SearchDebugState): string {
  const parts = [
    debug.providerName || debug.providerType,
    debug.mode,
    debug.channel ? `channel ${debug.channel}` : null,
    `${debug.durationMs} ms`,
    `${debug.resultCount} results`,
  ].filter(Boolean);
  return parts.join(" · ");
}

function SearchDebugDrawer({ debug }: { debug: SearchDebugState }) {
  const failedEntries = Object.entries(debug.failedQueries);

  return (
    <details className="mt-2 rounded-md border border-border-02 bg-background-neutral-02 px-3 py-2">
      <summary className="cursor-pointer list-none">
        <div className="flex flex-col gap-0.5">
          <Text as="p" text03 mainUiAction>
            Search debug
          </Text>
          <Text as="p" text04 mainUiMuted>
            {formatDebugSummary(debug)}
          </Text>
        </div>
      </summary>

      <div className="mt-3 flex flex-col gap-3">
        {debug.queries.length > 0 && (
          <div className="flex flex-col gap-1">
            <Text as="p" text04 mainUiAction>
              Queries
            </Text>
            <div className="flex flex-col gap-1">
              {debug.queries.map((query, index) => (
                <Text
                  key={`${query}-${index}`}
                  as="p"
                  text04
                  mainUiMuted
                  className="break-words"
                >
                  {query}
                </Text>
              ))}
            </div>
          </div>
        )}

        {debug.results.length > 0 && (
          <div className="flex flex-col gap-1">
            <Text as="p" text04 mainUiAction>
              Results
            </Text>
            <div className="flex flex-col gap-1">
              {debug.results.slice(0, 8).map((result, index) => (
                <Text
                  key={`${result.url}-${index}`}
                  as="p"
                  text04
                  mainUiMuted
                  className="break-words"
                >
                  {result.title ? `${result.title} — ${result.url}` : result.url}
                </Text>
              ))}
            </div>
          </div>
        )}

        {failedEntries.length > 0 && (
          <div className="flex flex-col gap-1">
            <Text as="p" text04 mainUiAction>
              Failed queries
            </Text>
            <div className="flex flex-col gap-1">
              {failedEntries.map(([query, error]) => (
                <Text
                  key={query}
                  as="p"
                  text04
                  mainUiMuted
                  className="break-words"
                >
                  {query}: {error}
                </Text>
              ))}
            </div>
          </div>
        )}

        {debug.error && (
          <div className="flex flex-col gap-1">
            <Text as="p" text04 mainUiAction>
              Error
            </Text>
            <Text as="p" text04 mainUiMuted className="break-words">
              {debug.error}
            </Text>
          </div>
        )}
      </div>
    </details>
  );
}

/**
 * WebSearchToolRenderer - Renders web search tool execution steps
 *
 * Only shows queries - results are handled by the fetch tool.
 *
 * RenderType modes:
 * - FULL: Shows queries timeline step. Used when step is expanded in timeline.
 * - HIGHLIGHT: Shows queries with header embedded directly in content.
 *              No StepContainer wrapper. Used for parallel streaming preview.
 * - INLINE: Shows queries for collapsed streaming view.
 */
export const WebSearchToolRenderer: MessageRenderer<SearchToolPacket, {}> = ({
  packets,
  onComplete,
  animate,
  stopPacketSeen,
  renderType,
  children,
}) => {
  const searchState = constructCurrentSearchState(packets);
  const { queries, debug } = searchState;

  const isHighlight = renderType === RenderType.HIGHLIGHT;
  const isInline = renderType === RenderType.INLINE;

  const queriesHeader = "Searching the web";

  if (queries.length === 0) {
    return children([
      {
        icon: SvgGlobe,
        status: "Searching the web",
        content: <div />,
        supportsCollapsible: false,
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
        supportsCollapsible: false,
        timelineLayout: "content",
        content: (
          <div className="flex flex-col">
            <Text as="p" text04 mainUiMuted className="mb-1">
              {queriesHeader}
            </Text>
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
          </div>
        ),
      },
    ]);
  }

  // INLINE mode: show queries for collapsed streaming view
  if (isInline) {
    return children([
      {
        icon: null,
        status: queriesHeader,
        supportsCollapsible: false,
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

  // FULL mode: return queries timeline step
  return children([
    {
      icon: SvgGlobe,
      status: "Searching the web",
      content: (
        <div className="flex flex-col">
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
          {debug && <SearchDebugDrawer debug={debug} />}
        </div>
      ),
      supportsCollapsible: false,
      timelineLayout: "timeline",
    },
  ]);
};
