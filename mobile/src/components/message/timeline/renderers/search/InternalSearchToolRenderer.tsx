// InternalSearchToolRenderer.tsx — the internal document search timeline step.
// Ported from web
//   web/src/app/app/message/messageComponents/timeline/renderers/search/InternalSearchToolRenderer.tsx
//
// Icon "search-menu", status "Searching internal documents".
//
// RenderType modes (mirrors web):
// - FULL:      query chips + a "Reading" label + result chips (one timeline step).
// - COMPACT:   results only (no queries, no "Reading" label). Header is the status.
// - HIGHLIGHT: muted in-content header + result chips, timelineLayout "content".
// - INLINE:    phase1 (no results yet) -> query chips under the queries header;
//              phase2 (has results) -> status "Reading" + result chips.
// Empty (no queries) -> a single step with empty content + BlinkingBar deferred
// to the chip list's empty state once querying begins.

import { View } from "react-native";

import { ValidSources, type OnyxDocument, type SearchToolPacket } from "@/lib/types";
import {
  RenderType,
  type MessageRendererProps,
} from "@/components/message/interfaces";
import { Text } from "@/components/opal";
import { BlinkingBar } from "@/components/message/BlinkingBar";
import {
  constructCurrentSearchState,
  INITIAL_QUERIES_TO_SHOW,
  QUERIES_PER_EXPANSION,
  INITIAL_RESULTS_TO_SHOW,
  RESULTS_PER_EXPANSION,
} from "@/state/timeline/searchStateUtils";
import { useFireOnComplete } from "@/state/timeline/hooks/useFireOnComplete";
import { SearchChipList, type ChipSource } from "./SearchChipList";

const QUERIES_HEADER = "Searching internal documents";

function queryToChip(query: string, index: number): ChipSource {
  return {
    id: `query-${index}`,
    title: query,
    sourceType: ValidSources.Web,
    isInternet: false,
  };
}

function resultToChip(doc: OnyxDocument): ChipSource {
  return {
    id: doc.document_id,
    title: doc.semantic_identifier || "",
    sourceType: doc.source_type,
    isInternet: doc.is_internet,
    url: doc.link ?? undefined,
  };
}

function resultKey(doc: OnyxDocument, index: number): string {
  return doc.document_id ?? `result-${index}`;
}

/**
 * Empty-state node for the result chip list. While streaming -> BlinkingBar;
 * once complete -> "No results found" (web used text-03 in FULL/COMPACT and
 * text-04 in HIGHLIGHT/INLINE; `emptyColor` preserves that distinction).
 */
function ResultsEmptyState({
  isComplete,
  emptyColor = "text-04",
}: {
  isComplete: boolean;
  emptyColor?: "text-03" | "text-04";
}) {
  if (!isComplete) return <BlinkingBar />;
  return (
    <Text font="main-ui-muted" color={emptyColor}>
      No results found
    </Text>
  );
}

export function InternalSearchToolRenderer({
  packets,
  onComplete,
  stopPacketSeen,
  renderType,
  children,
}: MessageRendererProps<SearchToolPacket>) {
  const { queries, results, isComplete } = constructCurrentSearchState(packets);

  useFireOnComplete(isComplete, onComplete);

  const isCompact = renderType === RenderType.COMPACT;
  const isHighlight = renderType === RenderType.HIGHLIGHT;
  const isInline = renderType === RenderType.INLINE;

  const hasResults = results.length > 0;

  if (queries.length === 0) {
    return children([
      {
        icon: "search-menu",
        status: QUERIES_HEADER,
        content: <View />,
        supportsCollapsible: true,
        timelineLayout: "timeline",
      },
    ]);
  }

  const renderResultChips = (emptyColor: "text-03" | "text-04") => (
    <SearchChipList
      items={results}
      initialCount={INITIAL_RESULTS_TO_SHOW}
      expansionCount={RESULTS_PER_EXPANSION}
      getKey={resultKey}
      toSourceInfo={resultToChip}
      emptyState={
        <ResultsEmptyState isComplete={isComplete} emptyColor={emptyColor} />
      }
    />
  );

  const queryChips = (
    <SearchChipList
      items={queries}
      initialCount={INITIAL_QUERIES_TO_SHOW}
      expansionCount={QUERIES_PER_EXPANSION}
      getKey={(_, index) => index}
      toSourceInfo={queryToChip}
      emptyState={!stopPacketSeen ? <BlinkingBar /> : undefined}
      isQuery
    />
  );

  // HIGHLIGHT: header embedded in content, no StepContainer (timelineLayout "content").
  if (isHighlight) {
    return children([
      {
        icon: null,
        status: null,
        supportsCollapsible: true,
        timelineLayout: "content",
        content: (
          <View style={{ gap: 4 }}>
            <Text font="main-ui-muted" color="text-04">
              {QUERIES_HEADER}
            </Text>
            {renderResultChips("text-04")}
          </View>
        ),
      },
    ]);
  }

  // INLINE: phase-based content for the collapsed streaming view.
  if (isInline) {
    if (!hasResults) {
      return children([
        {
          icon: null,
          status: QUERIES_HEADER,
          supportsCollapsible: true,
          timelineLayout: "content",
          content: queryChips,
        },
      ]);
    }

    return children([
      {
        icon: null,
        status: "Reading",
        supportsCollapsible: true,
        timelineLayout: "content",
        content: renderResultChips("text-04"),
      },
    ]);
  }

  // FULL and COMPACT: single combined step (queries + "Reading" + results).
  return children([
    {
      icon: "search-menu",
      status: QUERIES_HEADER,
      supportsCollapsible: true,
      timelineLayout: "timeline",
      content: (
        <View style={{ gap: 4 }}>
          {!isCompact && queryChips}
          {!isCompact && (
            <Text font="main-ui-muted" color="text-04">
              Reading
            </Text>
          )}
          {renderResultChips("text-03")}
        </View>
      ),
    },
  ]);
}

export default InternalSearchToolRenderer;
