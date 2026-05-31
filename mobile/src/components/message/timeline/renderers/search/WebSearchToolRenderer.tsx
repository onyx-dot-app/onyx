// WebSearchToolRenderer.tsx — the web search timeline step. Ported from web
//   web/src/app/app/message/messageComponents/timeline/renderers/search/WebSearchToolRenderer.tsx
//
// Icon "globe", status "Searching the web". Shows ONLY queries — results are
// handled by the fetch tool. Not collapsible (supportsCollapsible false).
//
// RenderType modes (mirrors web):
// - FULL:      query chips timeline step.
// - HIGHLIGHT: muted in-content "Searching the web" header + query chips,
//              timelineLayout "content".
// - INLINE:    query chips under the queries header, timelineLayout "content".
// Empty (no queries) -> a single step with empty content.

import { useEffect, useRef } from "react";
import { View } from "react-native";

import { ValidSources, type SearchToolPacket } from "@/lib/types";
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
} from "@/state/timeline/searchStateUtils";
import { SearchChipList, type ChipSource } from "./SearchChipList";

const QUERIES_HEADER = "Searching the web";

function queryToChip(query: string, index: number): ChipSource {
  return {
    id: `query-${index}`,
    title: query,
    sourceType: ValidSources.Web,
    isInternet: true,
  };
}

export function WebSearchToolRenderer({
  packets,
  onComplete,
  stopPacketSeen,
  renderType,
  children,
}: MessageRendererProps<SearchToolPacket>) {
  const { queries, isComplete } = constructCurrentSearchState(packets);

  const onCompleteFiredRef = useRef(false);
  useEffect(() => {
    if (isComplete && !onCompleteFiredRef.current) {
      onCompleteFiredRef.current = true;
      onComplete();
    }
  }, [isComplete, onComplete]);

  const isHighlight = renderType === RenderType.HIGHLIGHT;
  const isInline = renderType === RenderType.INLINE;

  if (queries.length === 0) {
    return children([
      {
        icon: "globe",
        status: QUERIES_HEADER,
        content: <View />,
        supportsCollapsible: false,
        timelineLayout: "timeline",
      },
    ]);
  }

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
        supportsCollapsible: false,
        timelineLayout: "content",
        content: (
          <View style={{ gap: 4 }}>
            <Text font="main-ui-muted" color="text-04">
              {QUERIES_HEADER}
            </Text>
            {queryChips}
          </View>
        ),
      },
    ]);
  }

  // INLINE: query chips for the collapsed streaming view.
  if (isInline) {
    return children([
      {
        icon: null,
        status: QUERIES_HEADER,
        supportsCollapsible: false,
        timelineLayout: "content",
        content: queryChips,
      },
    ]);
  }

  // FULL: query chips timeline step.
  return children([
    {
      icon: "globe",
      status: QUERIES_HEADER,
      content: queryChips,
      supportsCollapsible: false,
      timelineLayout: "timeline",
    },
  ]);
}

export default WebSearchToolRenderer;
