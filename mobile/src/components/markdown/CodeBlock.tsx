import { useCallback, useMemo } from "react";
import {
  Pressable,
  ScrollView,
  View,
  type ViewStyle,
} from "react-native";

import { Text } from "@/components/opal";
import { typography } from "@/theme/generated/typography";
import { radii } from "@/theme/generated/radii";
import { useThemeColors } from "@/theme/ThemeProvider";
import { useCopyToClipboard } from "@/lib/useCopyToClipboard";

interface CodeBlockProps {
  code: string;
  language?: string;
}

const CODE_SCROLL_CONTENT_STYLE = { padding: 12 } as const;

// Native mirror of web CodeBlock; wired as the fence/code_block rule in
// Markdown.tsx. Flat monospace — no syntax highlighting (see Markdown.tsx).
function CodeBlock({ code, language }: CodeBlockProps) {
  const colors = useThemeColors();
  const { copied, copy } = useCopyToClipboard();

  const handleCopy = useCallback(() => {
    if (!code) return;
    void copy(code);
  }, [code, copy]);

  const containerStyle = useMemo<ViewStyle>(
    () => ({
      backgroundColor: colors["background-code-01"],
      borderColor: colors["border-01"],
      borderWidth: 1,
      borderRadius: radii["12"],
      overflow: "hidden",
      width: "100%",
    }),
    [colors],
  );

  const headerStyle = useMemo<ViewStyle>(
    () => ({
      flexDirection: "row",
      alignItems: "center",
      justifyContent: "space-between",
      paddingHorizontal: 12,
      paddingVertical: 6,
      borderBottomColor: colors["border-01"],
      borderBottomWidth: 1,
    }),
    [colors],
  );

  const codeTextStyle = useMemo(
    () => [typography["main-content-mono"], { color: colors["code-code"] }],
    [colors],
  );

  return (
    <View style={containerStyle}>
      <View style={headerStyle}>
        <Text font="secondary-mono" color="text-03" numberOfLines={1}>
          {language || "code"}
        </Text>
        <Pressable
          onPress={handleCopy}
          accessibilityRole="button"
          accessibilityLabel={copied ? "Copied" : "Copy code"}
          hitSlop={8}
        >
          <Text font="secondary-action" color="text-03" numberOfLines={1}>
            {copied ? "Copied!" : "Copy"}
          </Text>
        </Pressable>
      </View>

      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={CODE_SCROLL_CONTENT_STYLE}
      >
        {/* Raw style array, not Opal Text, to avoid forced wrapping props. */}
        <Text style={codeTextStyle}>{code}</Text>
      </ScrollView>
    </View>
  );
}

export { CodeBlock, type CodeBlockProps };
