import { useMemo } from "react";
import {
  Linking,
  StyleSheet,
  Text as RNText,
  type TextStyle,
} from "react-native";
import RNMarkdown, {
  type ASTNode,
  type RenderRules,
} from "@ronradtke/react-native-markdown-display";

import { typography } from "@/theme/generated/typography";
import { radii } from "@/theme/generated/radii";
import { useThemeColors } from "@/theme/ThemeProvider";

import { CodeBlock } from "@/components/markdown/CodeBlock";
import { makeCitationLinkRule } from "@/components/message/citations/citationRule";
import type { CitationMap, OnyxDocument } from "@/lib/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * Visual variant:
 *  - "default": full body color (text-05), normal paragraph spacing.
 *  - "muted": muted body color (text-03), tighter spacing (timeline reasoning,
 *    expanded view) — mirrors web mutedTextMarkdownComponents.
 *  - "muted-collapsed": muted, no paragraph spacing — mirrors web
 *    collapsedMarkdownComponents.
 */
type MarkdownVariant = "default" | "muted" | "muted-collapsed";

interface MarkdownProps {
  /** The raw markdown source to render. */
  children: string;
  variant?: MarkdownVariant;
  /** citation_num -> document_id; when provided, inline [[N]](url) become pills. */
  citations?: CitationMap;
  /** Documents a citation resolves to (matched by document_id). */
  documents?: OnyxDocument[] | null;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Strip the trailing newline the markdown parser appends to fenced/indented
 * code blocks (mirrors the trimming the library's own default rules do).
 */
function trimTrailingNewline(content: string): string {
  if (content.length > 0 && content.charAt(content.length - 1) === "\n") {
    return content.substring(0, content.length - 1);
  }
  return content;
}

/**
 * Emoji-run splitter (capturing group so `String.split` keeps the matches).
 * `split` yields alternating [text, emoji, text, emoji, …] — odd indices are
 * emoji runs. Consecutive emoji (incl. ZWJ sequences, skin-tone + variation
 * selectors, keycaps, flags) collapse into one run via the trailing `+`.
 */
const EMOJI_RUN =
  /([\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}\u{2300}-\u{23FF}\u{2B00}-\u{2BFF}\u{1F1E6}-\u{1F1FF}\u{FE00}-\u{FE0F}\u{200D}\u{20E3}]+)/gu;

/** Drop `fontFamily` from a style so the run uses the system font. */
function withoutFontFamily(style: unknown): TextStyle {
  const rest = { ...((StyleSheet.flatten(style as TextStyle) ?? {}) as TextStyle) };
  delete rest.fontFamily;
  return rest;
}

/**
 * Render a markdown text node so emoji show as real color emoji.
 *
 * iOS pins a text run to the run's font, and the brand font HankenGrotesk has no
 * emoji glyphs (its `.notdef` "?" box even blocks the system emoji fallback). A
 * dedicated emoji family name isn't reliably resolvable in RN either. The robust
 * fix: render emoji runs with NO custom font in their ancestor chain so they use
 * the SYSTEM font (which renders color emoji), while keeping HankenGrotesk on the
 * non-emoji runs only. The outer wrapper therefore drops `fontFamily`; non-emoji
 * runs re-apply it; emoji runs are bare strings that inherit the (font-less)
 * wrapper. The matching `textgroup` override drops `fontFamily` one level up so
 * nothing in the chain re-imposes the brand font on the emoji runs.
 */
function renderTextWithEmoji(
  key: string,
  text: string,
  inheritedStyle: unknown,
): React.ReactNode {
  const flat = (StyleSheet.flatten(inheritedStyle as TextStyle) ??
    {}) as TextStyle;
  const segments = text.split(EMOJI_RUN);
  if (segments.length === 1) {
    return (
      <RNText key={key} style={flat}>
        {text}
      </RNText>
    );
  }
  const fontFamily = flat.fontFamily;
  const noFamily = withoutFontFamily(flat);
  return (
    <RNText key={key} style={noFamily}>
      {segments.map((seg, i) =>
        seg === "" ? null : i % 2 === 1 ? (
          // emoji run → bare string, inherits the font-less wrapper → system font
          seg
        ) : fontFamily ? (
          <RNText key={i} style={{ fontFamily }}>
            {seg}
          </RNText>
        ) : (
          seg
        ),
      )}
    </RNText>
  );
}

/**
 * Pull the language label off a fence node's info string. markdown-it stores
 * the fence info on `node.sourceInfo`; fall back to the `language-xxx` class on
 * `node.attributes` if present.
 */
function extractLanguage(node: ASTNode): string | undefined {
  const sourceInfo = (node as ASTNode & { sourceInfo?: string }).sourceInfo;
  if (typeof sourceInfo === "string" && sourceInfo.trim().length > 0) {
    // info strings can carry extra metadata after the language token.
    const lang = sourceInfo.trim().split(/\s+/)[0];
    return lang && lang.length > 0 ? lang : undefined;
  }
  return undefined;
}

// ---------------------------------------------------------------------------
// Markdown
// ---------------------------------------------------------------------------

/**
 * Chat markdown renderer. Wraps `react-native-markdown-display`'s `<Markdown>`
 * and derives its `styles` + `rules` maps from the Opal token system:
 *   - headings -> `heading-h1..h3` typography presets
 *   - body / paragraphs -> `main-content-body`
 *   - strong / em -> body preset with bold weight / italic style
 *   - links -> `action-text-link-05` token color, underlined
 *   - inline code -> `main-content-mono` mono preset on a tinted surface
 *   - blockquotes / lists -> body preset with token borders / colors
 *   - fenced & indented code blocks -> the `<CodeBlock>` component (copy button)
 *
 * Mirrors the FEATURE set of the web `MinimalMarkdown` (GFM, code blocks with
 * copy). FOLLOW-UP (out of scope here): syntax highlighting (web uses
 * rehype-highlight) and KaTeX math (web uses remark-math + rehype-katex) are
 * not yet implemented — code renders as flat monospace and `$...$` math renders
 * as plain text.
 */
function Markdown({
  children,
  variant = "default",
  citations,
  documents,
}: MarkdownProps) {
  const colors = useThemeColors();
  const muted = variant === "muted" || variant === "muted-collapsed";
  const bodyColor = muted ? colors["text-03"] : colors["text-05"];
  const paragraphSpacing =
    variant === "muted-collapsed" ? 0 : variant === "muted" ? 4 : 12;

  // Style map keyed by markdown node type. Text-bearing styles cascade onto
  // descendant text nodes via the library's inheritedStyles mechanism, so the
  // `body` preset propagates to paragraphs / list items / etc.
  const styles = useMemo(
    () => ({
      // Base text color + typography for the whole document.
      body: {
        ...typography["main-content-body"],
        color: bodyColor,
      },

      // Headings — Opal heading presets. The library wraps headings in a View,
      // so the typography needs to sit on the heading style (cascades to text).
      // Headings — keep the Opal heading FONT (HankenGrotesk SemiBold) but use
      // chat-appropriate sizes. The raw Opal `heading-h1` is a 48px hero size
      // (with a tight -0.48 letterSpacing tuned for that size); inside a chat
      // answer that's far too large, so size + letterSpacing are overridden.
      heading1: {
        ...typography["heading-h1"],
        fontSize: 22,
        lineHeight: 30,
        letterSpacing: -0.2,
        color: colors["text-05"],
        marginTop: 16,
        marginBottom: 8,
      },
      heading2: {
        ...typography["heading-h2"],
        fontSize: 19,
        lineHeight: 27,
        letterSpacing: -0.1,
        color: colors["text-05"],
        marginTop: 14,
        marginBottom: 6,
      },
      heading3: {
        ...typography["heading-h3"],
        fontSize: 17,
        lineHeight: 25,
        letterSpacing: 0,
        color: colors["text-05"],
        marginTop: 12,
        marginBottom: 6,
      },
      // h4-h6 have no dedicated Opal preset; step down from h3.
      heading4: {
        ...typography["heading-h3"],
        fontSize: 16,
        lineHeight: 24,
        letterSpacing: 0,
        color: colors["text-05"],
        marginTop: 12,
        marginBottom: 4,
      },
      heading5: {
        ...typography["heading-h3-muted"],
        fontSize: 15,
        lineHeight: 22,
        color: colors["text-04"],
        marginTop: 8,
        marginBottom: 4,
      },
      heading6: {
        ...typography["heading-h3-muted"],
        fontSize: 14,
        lineHeight: 20,
        color: colors["text-03"],
        marginTop: 8,
        marginBottom: 4,
      },

      // Paragraph spacing (the View wrapper; text color cascades from body).
      paragraph: {
        marginTop: 0,
        marginBottom: paragraphSpacing,
        flexWrap: "wrap" as const,
        flexDirection: "row" as const,
        alignItems: "center" as const,
        justifyContent: "flex-start" as const,
        width: "100%" as const,
      },

      // Emphasis.
      strong: {
        ...typography["main-content-emphasis"],
      },
      em: {
        fontStyle: "italic" as const,
      },
      s: {
        textDecorationLine: "line-through" as const,
      },

      // Links — Opal action/link token color.
      link: {
        color: colors["action-text-link-05"],
        textDecorationLine: "underline" as const,
      },

      // Lists.
      bullet_list: {
        marginBottom: 12,
      },
      ordered_list: {
        marginBottom: 12,
      },
      list_item: {
        flexDirection: "row" as const,
        justifyContent: "flex-start" as const,
      },

      // Blockquote — left rule + tinted surface using border/background tokens.
      blockquote: {
        backgroundColor: colors["background-tint-02"],
        borderColor: colors["border-02"],
        borderLeftWidth: 4,
        borderRadius: radii["04"],
        marginVertical: 8,
        paddingHorizontal: 12,
        paddingVertical: 4,
      },

      // Inline code — mono preset on a tinted, bordered chip.
      code_inline: {
        ...typography["main-content-mono"],
        color: colors["code-code"],
        backgroundColor: colors["background-tint-02"],
        borderColor: colors["border-01"],
        borderWidth: 1,
        borderRadius: radii["04"],
        paddingHorizontal: 4,
        paddingVertical: 1,
      },

      // Horizontal rule.
      hr: {
        backgroundColor: colors["border-01"],
        height: 1,
        marginVertical: 12,
      },

      // GFM tables — token-colored borders.
      table: {
        borderWidth: 1,
        borderColor: colors["border-01"],
        borderRadius: radii["08"],
        marginVertical: 8,
      },
      th: {
        flex: 1,
        padding: 6,
        ...typography["main-content-emphasis"],
        color: colors["text-05"],
      },
      tr: {
        borderBottomWidth: 1,
        borderColor: colors["border-01"],
        flexDirection: "row" as const,
      },
      td: {
        flex: 1,
        padding: 6,
      },
    }),
    [colors, bodyColor, paragraphSpacing],
  );

  // Override the fenced / indented code-block rules with our CodeBlock (which
  // adds the copy affordance). When citation data is provided, also override the
  // `link` rule so inline [[N]](url) markers render as CitationPills. Everything
  // else falls back to the library defaults (driven by the `styles` map above).
  const hasCitationData =
    citations !== undefined || (documents != null && documents.length > 0);
  const rules = useMemo<RenderRules>(
    () => ({
      fence: (node) => (
        <CodeBlock
          key={node.key}
          code={trimTrailingNewline(node.content)}
          language={extractLanguage(node)}
        />
      ),
      code_block: (node) => (
        <CodeBlock key={node.key} code={trimTrailingNewline(node.content)} />
      ),
      // Emoji handling (see renderTextWithEmoji): emoji must render in the
      // system font, so we drop the brand `fontFamily` at BOTH the textgroup
      // (one level up) and the text node, re-applying it only to non-emoji runs.
      textgroup: (node, children, _parent, _styles, inheritedStyles = {}) => (
        <RNText key={node.key} style={withoutFontFamily(inheritedStyles)}>
          {children}
        </RNText>
      ),
      text: (node, _children, _parent, _styles, inheritedStyles = {}) =>
        renderTextWithEmoji(node.key, node.content, inheritedStyles),
      ...(hasCitationData
        ? { link: makeCitationLinkRule({ citations, documents }) }
        : {}),
    }),
    [hasCitationData, citations, documents],
  );

  return (
    // The library typing wraps StyleSheet.NamedStyles which is stricter than
    // our literal style map (it carries token-driven values); the runtime
    // accepts it fine, so cast through unknown for the style prop.
    <RNMarkdown
      style={styles as never}
      rules={rules}
      onLinkPress={(url) => {
        void Linking.openURL(url);
        return false;
      }}
    >
      {children}
    </RNMarkdown>
  );
}

export { Markdown, type MarkdownProps };
