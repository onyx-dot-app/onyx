// streamdown wraps enriched-markdown (worklet parsing), which needs concrete style values, not NativeWind
// classes — so resolve Onyx tokens from the shared vars/presets here. Swapping the markdown lib touches
// only this file.
import { useMemo } from "react";
import { useColorScheme } from "react-native";
import { StreamdownText } from "react-native-streamdown";
import type { MarkdownStyle } from "react-native-enriched-markdown";
import { textPresets, varsDark, varsLight } from "@onyx-ai/shared/native";

interface StreamingMarkdownProps {
  content: string;
  isStreaming: boolean;
}

const BODY = textPresets["main-content-body"];
const MONO = textPresets["main-content-mono"];

// Markdown element styles as concrete values (enriched-markdown takes literals, not NativeWind
// classes): Onyx tokens on a 16px body base; heading/code sizes are fixed pixels.
function buildMarkdownStyle(scheme: "light" | "dark"): MarkdownStyle {
  const vars = scheme === "dark" ? varsDark : varsLight;
  const color = (token: string): string => vars[token] ?? "#000000";
  // Fenced code has no Onyx token; use the Atom One base color (one flat color — no per-token highlighting).
  const codeBaseColor = scheme === "dark" ? "#e2e6eb" : "#383a42";
  return {
    paragraph: {
      color: color("--text-05"),
      fontFamily: BODY.fontFamily,
      fontSize: BODY.fontSize,
      lineHeight: BODY.lineHeight,
      // marginTop 0: RN doesn't collapse margins, so 0 top + 8 bottom gives an even 8px rhythm.
      marginTop: 0,
      marginBottom: 8,
    },
    h1: {
      color: color("--text-05"),
      fontFamily: BODY.fontFamily,
      fontSize: 36,
      fontWeight: "800",
      lineHeight: 40,
      marginTop: 27,
      marginBottom: 18,
    },
    h2: {
      color: color("--text-05"),
      fontFamily: BODY.fontFamily,
      fontSize: 24,
      fontWeight: "700",
      lineHeight: 32,
      marginTop: 18,
      marginBottom: 12,
    },
    h3: {
      color: color("--text-05"),
      fontFamily: BODY.fontFamily,
      fontSize: 20,
      fontWeight: "600",
      lineHeight: 32,
      marginTop: 15,
      marginBottom: 10,
    },
    strong: { color: color("--text-05"), fontWeight: "bold" },
    // No color: italics inherit their block color (paragraph/list text-05, blockquote text-04).
    em: { fontStyle: "italic" },
    link: { color: color("--action-link-05"), underline: true },
    list: {
      color: color("--text-05"),
      markerColor: color("--text-03"),
      fontFamily: BODY.fontFamily,
      fontSize: BODY.fontSize,
      lineHeight: BODY.lineHeight,
    },
    code: {
      fontFamily: MONO.fontFamily,
      fontSize: 12,
      color: color("--text-05"),
      backgroundColor: color("--background-tint-00"),
    },
    codeBlock: {
      fontFamily: MONO.fontFamily,
      fontSize: 12,
      color: codeBaseColor,
      backgroundColor: color("--background-code-01"),
      // No border; the card background + rounded-12 give code blocks their shape.
      borderRadius: 12,
      padding: 8,
    },
    blockquote: {
      color: color("--text-04"),
      borderColor: color("--border-02"),
      borderWidth: 4,
      gapWidth: 16,
    },
    thematicBreak: {
      color: color("--border-02"),
      height: 1,
      marginTop: 20,
      marginBottom: 16,
    },
    // The library draws a full grid; the neutral-01 card + token borders keep it theme-correct.
    table: {
      color: color("--text-05"),
      borderColor: color("--border-01"),
      borderWidth: 1,
      borderRadius: 8,
      headerTextColor: color("--text-05"),
      headerBackgroundColor: color("--background-neutral-01"),
      rowEvenBackgroundColor: color("--background-neutral-01"),
      rowOddBackgroundColor: color("--background-neutral-01"),
    },
  };
}

export function StreamingMarkdown({
  content,
  isStreaming,
}: StreamingMarkdownProps) {
  const scheme = useColorScheme() === "dark" ? "dark" : "light";
  const markdownStyle = useMemo(() => buildMarkdownStyle(scheme), [scheme]);
  return (
    <StreamdownText
      markdown={content}
      markdownStyle={markdownStyle}
      flavor="github"
      // no selection mid-stream — growing content fights an active selection
      selectable={!isStreaming}
    />
  );
}
