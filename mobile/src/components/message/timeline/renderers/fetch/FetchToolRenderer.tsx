// FetchToolRenderer.tsx — renders URL fetch/open ("Reading") tool steps.
//
// Ported from web:
//   web/src/app/app/message/messageComponents/timeline/renderers/fetch/FetchToolRenderer.tsx
//
// RenderType modes:
// - FULL / COMPACT: icon "circle", status "Reading". Body is the doc/URL chips
//   (the timeline shell draws the "Reading" header from `status`).
// - HIGHLIGHT: header embedded in content as a text-02 "Reading" line
//   (timelineLayout "content"); no StepContainer chrome.
//
// Body content priority (mirrors web):
//   documents present        -> document chips
//   else complete & has URLs -> URL chips
//   else                     -> BlinkingBar (while still streaming)
//
// AMENDMENT: web reuses `SearchChipList` for the chips. That component is not
// ported yet, so we render an inline flex-wrap of chips here (SourceIcon +
// truncated title) with the same INITIAL_URLS_TO_SHOW / URLS_PER_EXPANSION
// "show more" behavior. Docs/URLs open via `Linking.openURL` (web used
// `window.open(_, "_blank")`).

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Linking, Pressable, View } from "react-native";

import { type FetchToolPacket, type OnyxDocument } from "@/lib/types";
import {
  RenderType,
  type MessageRendererProps,
} from "@/components/message/interfaces";
import {
  constructCurrentFetchState,
  INITIAL_URLS_TO_SHOW,
  URLS_PER_EXPANSION,
} from "@/state/timeline/fetchStateUtils";
import { BlinkingBar } from "@/components/message/BlinkingBar";
import { SourceIcon } from "@/components/message/sources/SourceIcon";
import { truncateText } from "@/components/message/sources/sourceInfo";
import { Text } from "@/components/opal";
import { useToken } from "@/theme/ThemeProvider";
import { radii } from "@/theme/generated/radii";
import { timelineTokens as T } from "@/theme/timelineTokens";

// ---------------------------------------------------------------------------
// Chip — a single document/URL pill (SourceIcon + truncated title).
// ---------------------------------------------------------------------------

interface ChipProps {
  title: string;
  sourceType?: string;
  isInternet?: boolean;
  onPress: () => void;
}

function Chip({ title, sourceType, isInternet, onPress }: ChipProps) {
  const borderColor = useToken("border-02");
  const backgroundColor = useToken("background-neutral-01");

  return (
    <Pressable
      onPress={onPress}
      style={{
        flexDirection: "row",
        alignItems: "center",
        gap: 4,
        paddingHorizontal: 8,
        paddingVertical: 4,
        borderRadius: radii["full"],
        borderWidth: 1,
        borderColor,
        backgroundColor,
        maxWidth: "100%",
      }}
    >
      <SourceIcon size={12} color="text-03" sourceType={sourceType} isInternet={isInternet} />
      <Text font="secondary-body" color="text-03" numberOfLines={1} style={{ flexShrink: 1 }}>
        {truncateText(title)}
      </Text>
    </Pressable>
  );
}

// ---------------------------------------------------------------------------
// ChipList — inline flex-wrap of chips with "show more" expansion.
// Mirrors web SearchChipList's INITIAL_URLS_TO_SHOW / URLS_PER_EXPANSION.
// ---------------------------------------------------------------------------

interface ChipListProps {
  items: ChipProps[];
  emptyState?: React.ReactNode;
}

function ChipList({ items, emptyState }: ChipListProps) {
  const [visibleCount, setVisibleCount] = useState(INITIAL_URLS_TO_SHOW);

  if (items.length === 0) {
    return emptyState ? <>{emptyState}</> : null;
  }

  const visible = items.slice(0, visibleCount);
  const remaining = items.length - visible.length;

  return (
    <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
      {visible.map((item, index) => (
        <Chip key={`${item.title}-${index}`} {...item} />
      ))}
      {remaining > 0 && (
        <Pressable
          onPress={() =>
            setVisibleCount((count) => count + URLS_PER_EXPANSION)
          }
          style={{ paddingHorizontal: 8, paddingVertical: 4 }}
        >
          <Text font="secondary-body" color="text-03">
            +{remaining} more
          </Text>
        </Pressable>
      )}
    </View>
  );
}

// ---------------------------------------------------------------------------
// FetchToolRenderer
// ---------------------------------------------------------------------------

const READING_STATUS = "Reading";

export function FetchToolRenderer({
  packets,
  onComplete,
  stopPacketSeen,
  renderType,
  children,
}: MessageRendererProps<FetchToolPacket>) {
  const fetchState = useMemo(
    () => constructCurrentFetchState(packets),
    [packets]
  );
  const { urls, documents, hasStarted, isComplete } = fetchState;
  const isHighlight = renderType === RenderType.HIGHLIGHT;

  const headerColor = useToken("text-02");

  // Fire onComplete once when the tool finishes (mobile timeline-shell contract).
  const completeFiredRef = useRef(false);
  useEffect(() => {
    if (isComplete && !completeFiredRef.current) {
      completeFiredRef.current = true;
      onComplete();
    }
  }, [isComplete, onComplete]);

  const openDoc = useCallback((doc: OnyxDocument) => {
    if (doc.link) Linking.openURL(doc.link).catch(() => undefined);
  }, []);

  const openUrl = useCallback((url: string) => {
    Linking.openURL(url).catch(() => undefined);
  }, []);

  const displayDocuments = documents.length > 0;
  const displayUrls = !displayDocuments && isComplete && urls.length > 0;

  const documentChips = useMemo<ChipProps[]>(
    () =>
      documents.map((doc) => ({
        title: doc.semantic_identifier || doc.link || "",
        sourceType: doc.source_type,
        isInternet: doc.is_internet,
        onPress: () => openDoc(doc),
      })),
    [documents, openDoc]
  );

  const urlChips = useMemo<ChipProps[]>(
    () =>
      urls.map((url) => ({
        title: url,
        isInternet: true,
        onPress: () => openUrl(url),
      })),
    [urls, openUrl]
  );

  // Not started yet — empty "Reading" placeholder step.
  if (!hasStarted) {
    return children([
      {
        icon: "circle",
        status: READING_STATUS,
        content: <View />,
        supportsCollapsible: false,
        timelineLayout: "timeline",
      },
    ]);
  }

  const chips = displayDocuments ? (
    <ChipList
      items={documentChips}
      emptyState={!stopPacketSeen ? <BlinkingBar /> : undefined}
    />
  ) : displayUrls ? (
    <ChipList
      items={urlChips}
      emptyState={!stopPacketSeen ? <BlinkingBar /> : undefined}
    />
  ) : (
    !stopPacketSeen && <BlinkingBar />
  );

  // HIGHLIGHT mode: header embedded in content, no StepContainer chrome.
  if (isHighlight) {
    return children([
      {
        icon: null,
        status: null,
        supportsCollapsible: false,
        timelineLayout: "content",
        content: (
          <View style={{ flexDirection: "column" }}>
            <Text
              font="secondary-body"
              style={{ color: headerColor, marginBottom: 4 }}
            >
              {READING_STATUS}
            </Text>
            {chips}
          </View>
        ),
      },
    ]);
  }

  return children([
    {
      icon: "circle",
      status: READING_STATUS,
      supportsCollapsible: false,
      timelineLayout: "timeline",
      content: (
        <View
          style={{
            flexDirection: "column",
            paddingLeft: T.timelineCommonTextPadding,
          }}
        >
          {chips}
        </View>
      ),
    },
  ]);
}

export default FetchToolRenderer;
