// Native mirror of web SearchChipList; web's Opal SourceTag (favicon + hover
// card) becomes a plain Pressable pill (no hover on mobile).

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

export interface ChipSource {
  id: string;
  title: string;
  sourceType: string;
  isInternet?: boolean;
  url?: string;
}

export interface SearchChipListProps<T> {
  items: T[];
  initialCount: number;
  expansionCount: number;
  getKey: (item: T, index: number) => string | number;
  toSourceInfo: (item: T, index: number) => ChipSource;
  onClick?: (item: T) => void;
  emptyState?: React.ReactNode;
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
        // Stable keys = animate on MOUNT only, so existing chips never re-animate
        // when the list grows (RN equivalent of web's `animatedKeysRef`). Stagger
        // is capped to one expansion batch to bound the delay.
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
      {/* Single line + shrink so a long label stays on the same row as the icon
          instead of wrapping below it. */}
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
