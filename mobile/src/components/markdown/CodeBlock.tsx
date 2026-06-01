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

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface CodeBlockProps {
  /** The raw code text (already stripped of the trailing newline by the parser). */
  code: string;

  /**
   * Optional language label (from the fence info string, e.g. ```ts -> "ts").
   * Shown in the header next to the copy affordance.
   */
  language?: string;
}

const CODE_SCROLL_CONTENT_STYLE = { padding: 12 } as const;

// ---------------------------------------------------------------------------
// CodeBlock
// ---------------------------------------------------------------------------

/**
 * Native mirror of the web `CodeBlock` (web/src/app/app/message/CodeBlock.tsx),
 * mirroring its FEATURES rather than its implementation:
 *   - monospace code rendered with the Opal `main-content-mono` typography preset
 *   - code-token colors (`background-code-01` surface, `code-code` text)
 *   - a header showing the language label and a copy affordance
 *
 * Full syntax highlighting (rehype-highlight on web) and KaTeX math are OUT OF
 * SCOPE here — code is rendered as flat monospace text. See the follow-up note
 * in Markdown.tsx.
 *
 * Wired as the `fence` / `code_block` rule in Markdown.tsx.
 */
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

  // `main-content-mono` is the DMMono preset; pair it with the `code-code`
  // token for the code-foreground color.
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
        {/* RN Text (via Opal would force wrapping props); use a raw style array
            so the monospace preset + code color cascade onto the code text. */}
        <Text style={codeTextStyle}>{code}</Text>
      </ScrollView>
    </View>
  );
}

export { CodeBlock, type CodeBlockProps };
