// SearchChipList.tsx — a wrapping row of source/query chips for the search
// renderers. Native mirror of web SearchChipList.
//
// Web renders each chip via the Opal `SourceTag` (favicon/connector glyph +
// truncated label, hover details card + tooltip). Mobile has no SourceTag, so a
// chip is a plain Pressable pill: a SourceIcon (or SvgSearch for query chips) +
// a truncated title on a tinted pill background. Result chips open `url` via
// Linking; query chips are not pressable
// to a doc. The hover details card and tooltip are dropped (no hover on mobile).
//
// Expansion: visibleCount starts at `initialCount` and grows by `expansionCount`
// per "+N more" press, mirroring the web reducer. Newly-added chips fade/slide
// in via a Reanimated `entering` animation that fires only on MOUNT. Because
// each chip has a stable `key`, React preserves the instance across re-renders,
// so existing chips never re-animate when the list grows — the RN-idiomatic
// equivalent of web's `animatedKeysRef` set (and lint-safe: no ref read during
// render).

import { useMemo, useState } from "react";
import { Linking, Pressable, View } from "react-native";
import Animated, { FadeInLeft } from "react-native-reanimated";

import { Text } from "@/components/opal";
import { SvgSearch } from "@/components/icons";
import { SourceIcon } from "@/components/message/sources/SourceIcon";
import { truncateText } from "@/components/message/sources/sourceInfo";
import { MAX_TITLE_LENGTH } from "@/state/timeline/searchStateUtils";
import { useThemeColors } from "@/theme/ThemeProvider";
import { radii } from "@/theme/generated/radii";

const ANIMATION_DELAY_MS = 30;

/** Descriptor for one chip, produced by the renderer's `toSourceInfo`. */
export interface ChipSource {
  /** Stable id (unused for layout, kept for parity with web SourceInfo). */
  id: string;
  /** Display label (truncated before render). */
  title: string;
  /** Connector source_type, drives the SourceIcon glyph for result chips. */
  sourceType: string;
  /** Web/internet source — globe glyph. */
  isInternet?: boolean;
  /** External link opened on press (result chips only). */
  url?: string;
}

export interface SearchChipListProps<T> {
  items: T[];
  initialCount: number;
  expansionCount: number;
  getKey: (item: T, index: number) => string | number;
  toSourceInfo: (item: T, index: number) => ChipSource;
  /** Result chips: invoked on press (web opened doc.link in a new tab). */
  onClick?: (item: T) => void;
  /** Rendered when there are no items (e.g. BlinkingBar / "No results found"). */
  emptyState?: React.ReactNode;
  /** Query chips render the SvgSearch glyph and are not pressable to a doc. */
  isQuery?: boolean;
}

type DisplayEntry<T> =
  | { type: "chip"; item: T; index: number }
  | { type: "more" };

export function SearchChipList<T>({
  items,
  initialCount,
  expansionCount,
  getKey,
  toSourceInfo,
  onClick,
  emptyState,
  isQuery = false,
}: SearchChipListProps<T>) {
  const [visibleCount, setVisibleCount] = useState(initialCount);

  const effectiveCount = Math.min(visibleCount, items.length);

  const displayList: DisplayEntry<T>[] = useMemo(() => {
    const chips: DisplayEntry<T>[] = items
      .slice(0, effectiveCount)
      .map((item, i) => ({ type: "chip" as const, item, index: i }));
    if (effectiveCount < items.length) {
      chips.push({ type: "more" });
    }
    return chips;
  }, [items, effectiveCount]);

  const remainingCount = items.length - effectiveCount;

  function handleShowMore() {
    setVisibleCount((prev) => prev + expansionCount);
  }

  if (items.length === 0) {
    return <View style={{ flexDirection: "row" }}>{emptyState}</View>;
  }

  return (
    <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
      {displayList.map((entry) => {
        // Each chip animates on MOUNT only. React keeps the instance for stable
        // keys across re-renders, so existing chips never re-animate when the
        // list grows (the RN equivalent of web's `animatedKeysRef`). The stagger
        // is derived from the entry index (capped to one expansion batch so a
        // long list never accrues unbounded delay).
        const key =
          entry.type === "more"
            ? "more-button"
            : String(getKey(entry.item, entry.index));
        const staggerIndex =
          entry.type === "more"
            ? 0
            : entry.index % Math.max(expansionCount, 1);
        const entering = FadeInLeft.duration(150).delay(
          staggerIndex * ANIMATION_DELAY_MS
        );

        if (entry.type === "more") {
          return (
            <Animated.View key={key} entering={entering}>
              <Chip
                label={`+${remainingCount} more`}
                isQuery={isQuery}
                onPress={handleShowMore}
              />
            </Animated.View>
          );
        }

        const info = toSourceInfo(entry.item, entry.index);
        const canOpen = !isQuery && (onClick != null || info.url != null);

        return (
          <Animated.View key={key} entering={entering}>
            <Chip
              label={truncateText(info.title, MAX_TITLE_LENGTH)}
              sourceType={info.sourceType}
              isInternet={info.isInternet}
              isQuery={isQuery}
              onPress={
                canOpen
                  ? () => {
                      if (onClick) onClick(entry.item);
                      else if (info.url) {
                        void Linking.openURL(info.url);
                      }
                    }
                  : undefined
              }
            />
          </Animated.View>
        );
      })}
    </View>
  );
}

interface ChipProps {
  label: string;
  sourceType?: string;
  isInternet?: boolean;
  isQuery?: boolean;
  onPress?: () => void;
}

/** A single pill: leading glyph + truncated label on a tinted rounded surface. */
function Chip({ label, sourceType, isInternet, isQuery, onPress }: ChipProps) {
  const colors = useThemeColors();
  const iconColor = colors["text-03"];

  return (
    <Pressable
      onPress={onPress}
      disabled={onPress == null}
      style={({ pressed }) => ({
        flexDirection: "row",
        alignItems: "center",
        gap: 4,
        paddingHorizontal: 8,
        paddingVertical: 4,
        borderRadius: radii["08"],
        backgroundColor: colors["background-tint-02"],
        opacity: pressed && onPress != null ? 0.7 : 1,
      })}
    >
      {isQuery ? (
        <SvgSearch size={14} color={iconColor} />
      ) : (
        <SourceIcon
          sourceType={sourceType}
          isInternet={isInternet}
          size={14}
          color={iconColor}
        />
      )}
      {/* Single line + shrink so the icon and label stay on the SAME row; a long
          query inside the narrow timeline column would otherwise wrap below the
          (vertically-centered) icon and read as "icon on top, text below". */}
      <Text
        font="secondary-body"
        color="text-04"
        numberOfLines={1}
        style={{ flexShrink: 1 }}
      >
        {label}
      </Text>
    </Pressable>
  );
}

export default SearchChipList;
