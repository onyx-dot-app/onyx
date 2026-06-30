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

// Mirrors the web chat renderer (`prose prose-onyx` + the MemoizedParagraph/CodeBlock component
// overrides). Each token below is the one web actually resolves per element; sizes are web's
// computed pixels (prose base = 16px). Web sources: prose vars in custom-code-styles.css, heading
// sizes from Tailwind Typography defaults, margins from globals.css `.prose` overrides, inline/code
// from CodeBlock.tsx.
function buildMarkdownStyle(scheme: "light" | "dark"): MarkdownStyle {
  const vars = scheme === "dark" ? varsDark : varsLight;
  const color = (token: string): string => vars[token] ?? "#000000";
  // Fenced code has no Onyx token on web — it shows the `.hljs` base color (Atom One Light/Dark)
  // from custom-code-styles.css. We can't reproduce per-token syntax highlighting with the single
  // flat color this library exposes, so mirror that base literal as the closest match.
  const codeBaseColor = scheme === "dark" ? "#e2e6eb" : "#383a42";
  return {
    paragraph: {
      color: color("--text-05"),
      fontFamily: BODY.fontFamily,
      fontSize: BODY.fontSize,
      lineHeight: BODY.lineHeight,
      // marginTop 0 (not web's 0.5em): RN doesn't collapse margins, so 0/8 yields web's collapsed
      // 8px inter-paragraph rhythm and matches the `.prose > :first-child` zero top margin.
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
    // No color: like web, italics inherit their block color (paragraph/list text-05, blockquote text-04).
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
      // Web code blocks have no border; the tint-00 card + rounded-12 give them shape.
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
    // Web tables sit on a `--background-neutral-01` card (ScrollableTable) with prose grey borders.
    // The library draws a full grid (web uses horizontal rules only), but tokens keep it theme-correct.
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
