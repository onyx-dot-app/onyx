// CitationPill.tsx — inline citation chip. Mirrors web SourceTag variant
// "inlineCitation": optional +N count, no leading icon. Press opens the citation
// detail sheet (mobile press state mirrors web's open state).

import { Pressable, View } from "react-native";

import { Text } from "@/components/opal";
import { useThemeColors } from "@/theme/ThemeProvider";
import { radii } from "@/theme/generated/radii";
import { useCitationSheet } from "@/components/message/sources/CitationSheet";
import type { SourceInfo } from "@/components/message/sources/sourceInfo";

interface CitationPillProps {
  label: string;
  /** Extra-source count for the "+N" suffix (sources beyond the first). */
  extraCount?: number;
  /** Sources opened in the detail sheet on press. */
  sources?: SourceInfo[];
  /** When false, renders a static (non-tappable) chip — used for [Q] markers. */
  interactive?: boolean;
}

export function CitationPill({
  label,
  extraCount = 0,
  sources,
  interactive = true,
}: CitationPillProps) {
  const colors = useThemeColors();
  const sheet = useCitationSheet();

  const body = (pressed: boolean) => {
    const bg = pressed
      ? colors["background-tint-inverted-03"]
      : colors["background-tint-02"];
    const fg = pressed ? "text-inverted-05" : "text-03";
    return (
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          alignSelf: "flex-start",
          gap: 2,
          paddingHorizontal: 4,
          paddingVertical: 2,
          marginRight: 2,
          borderRadius: radii["04"],
          backgroundColor: bg,
        }}
      >
        <Text font="figure-small-value" color={fg} numberOfLines={1}>
          {label}
        </Text>
        {extraCount > 0 && (
          <Text font="figure-small-value" color={fg}>
            +{extraCount}
          </Text>
        )}
      </View>
    );
  };

  if (!interactive) {
    return body(false);
  }

  return (
    <Pressable
      onPress={() => {
        if (sources && sources.length > 0) sheet.present(sources);
      }}
      hitSlop={6}
      accessibilityRole="link"
    >
      {({ pressed }) => body(pressed)}
    </Pressable>
  );
}

export default CitationPill;
