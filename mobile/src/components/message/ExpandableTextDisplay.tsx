// ExpandableTextDisplay.tsx — collapsible long-form text with a maximize -> full
// bottom-sheet. Ports web ExpandableTextDisplay (Radix modal -> @gorhom sheet;
// CSS line-clamp/translateY -> measured max-height clamp + translateY).
//
// Collapsed content is clipped to `maxLines` of height; overflow is measured via
// the child's onLayout height. While streaming, the latest lines are
// bottom-anchored (content translated up) with a top "…" indicator.

import { useRef, useState, type ReactNode } from "react";
import { View, Pressable } from "react-native";
import { BottomSheetScrollView } from "@gorhom/bottom-sheet";

import { BottomSheet, type BottomSheetRef, Text } from "@/components/opal";
import { useThemeColors } from "@/theme/ThemeProvider";
import { radii } from "@/theme/generated/radii";
import { SvgMaximize2, SvgCopy, SvgCheck } from "@/components/icons";
import { useCopyToClipboard } from "@/lib/useCopyToClipboard";

const LINE_HEIGHT = 20;

interface ExpandableTextDisplayProps {
  /** Sheet title. */
  title: string;
  /** Full content (for the expanded sheet + copy). */
  content: string;
  /** Collapsed preview content (defaults to `content`). */
  displayContent?: string;
  /** Max lines shown collapsed. */
  maxLines?: number;
  /** Render markdown/text for a given string + expanded flag. */
  renderContent: (text: string, isExpanded: boolean) => ReactNode;
  /** True while the source is still streaming (bottom-anchor + top ellipsis). */
  isStreaming?: boolean;
}

export function ExpandableTextDisplay({
  title,
  content,
  displayContent,
  maxLines = 8,
  renderContent,
  isStreaming = false,
}: ExpandableTextDisplayProps) {
  const colors = useThemeColors();
  const sheetRef = useRef<BottomSheetRef>(null);
  const [childHeight, setChildHeight] = useState(0);
  const { copied, copy } = useCopyToClipboard();

  const collapsedMaxHeight = maxLines * LINE_HEIGHT;
  const isOverflowing = childHeight > collapsedMaxHeight + 1;
  const preview = displayContent ?? content;

  // While streaming + overflowing, shift content up so the newest lines show.
  const translateY =
    isStreaming && isOverflowing ? -(childHeight - collapsedMaxHeight) : 0;

  return (
    <View>
      {isStreaming && isOverflowing && (
        <Text font="secondary-body" color="text-03" style={{ marginBottom: 2 }}>
          …
        </Text>
      )}

      <View style={{ flexDirection: "row", alignItems: "flex-start" }}>
        <View
          style={{ flex: 1, maxHeight: collapsedMaxHeight, overflow: "hidden" }}
        >
          <View
            style={{ transform: [{ translateY }] }}
            onLayout={(e) => setChildHeight(e.nativeEvent.layout.height)}
          >
            {renderContent(preview, false)}
          </View>
        </View>

        {isOverflowing && (
          <Pressable
            onPress={() => sheetRef.current?.present()}
            hitSlop={8}
            accessibilityRole="button"
            style={{ padding: 4, marginLeft: 2 }}
          >
            <SvgMaximize2 size={16} color="text-03" />
          </Pressable>
        )}
      </View>

      <BottomSheet ref={sheetRef} snapPoints={["75%"]} enablePanDownToClose>
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            justifyContent: "space-between",
            paddingHorizontal: 16,
            paddingBottom: 8,
          }}
        >
          <Text font="heading-h3" color="text-04" numberOfLines={1} style={{ flex: 1 }}>
            {title}
          </Text>
          <Pressable
            onPress={() => void copy(content)}
            hitSlop={8}
            style={{
              flexDirection: "row",
              alignItems: "center",
              gap: 4,
              backgroundColor: colors["background-tint-02"],
              borderRadius: radii["08"],
              paddingHorizontal: 10,
              paddingVertical: 6,
            }}
          >
            {copied ? (
              <SvgCheck size={14} color="text-03" />
            ) : (
              <SvgCopy size={14} color="text-03" />
            )}
            <Text font="secondary-action" color="text-03">
              {copied ? "Copied!" : "Copy"}
            </Text>
          </Pressable>
        </View>
        <BottomSheetScrollView
          contentContainerStyle={{ paddingHorizontal: 16, paddingBottom: 32 }}
        >
          {renderContent(content, true)}
        </BottomSheetScrollView>
      </BottomSheet>
    </View>
  );
}

export default ExpandableTextDisplay;
