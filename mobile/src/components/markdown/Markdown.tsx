import { useMemo } from "react";
import { Linking } from "react-native";
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

// EMOJI NOTE: the chat answer renders in the SYSTEM font (no `fontFamily` on the
// text styles below — only `fontWeight`). The Opal brand font HankenGrotesk has
// no emoji glyphs and ships a `.notdef` "?" box that wins over iOS's per-glyph
// emoji fallback, so any emoji the model emits rendered as tofu. iOS won't
// resolve a named emoji font in RN, and the markdown library applies the body/
// heading font on a Text ancestor of every run, so emoji can only render when no
// custom font is in the chain at all. Using the system font keeps emoji working
// while preserving size + weight; UI chrome elsewhere still uses HankenGrotesk.

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
      // Base text color + typography for the whole document. NB: NO `fontFamily`
      // (system font) so emoji render — see EMOJI NOTE above. `fontFamily:
      // undefined` clears the brand family the preset spread would set; weight is
      // carried explicitly via `fontWeight`.
      body: {
        ...typography["main-content-body"],
        fontFamily: undefined,
        fontWeight: "500" as const,
        color: bodyColor,
      },

      // Headings — chat-appropriate sizes (the raw Opal `heading-h1` is a 48px
      // hero size). System font (no fontFamily) + explicit weight so emoji render.
      heading1: {
        ...typography["heading-h1"],
        fontFamily: undefined,
        fontWeight: "600" as const,
        fontSize: 22,
        lineHeight: 30,
        letterSpacing: -0.2,
        color: colors["text-05"],
        marginTop: 16,
        marginBottom: 8,
      },
      heading2: {
        ...typography["heading-h2"],
        fontFamily: undefined,
        fontWeight: "600" as const,
        fontSize: 19,
        lineHeight: 27,
        letterSpacing: -0.1,
        color: colors["text-05"],
        marginTop: 14,
        marginBottom: 6,
      },
      heading3: {
        ...typography["heading-h3"],
        fontFamily: undefined,
        fontWeight: "600" as const,
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
        fontFamily: undefined,
        fontWeight: "600" as const,
        fontSize: 16,
        lineHeight: 24,
        letterSpacing: 0,
        color: colors["text-05"],
        marginTop: 12,
        marginBottom: 4,
      },
      heading5: {
        ...typography["heading-h3-muted"],
        fontFamily: undefined,
        fontWeight: "500" as const,
        fontSize: 15,
        lineHeight: 22,
        color: colors["text-04"],
        marginTop: 8,
        marginBottom: 4,
      },
      heading6: {
        ...typography["heading-h3-muted"],
        fontFamily: undefined,
        fontWeight: "500" as const,
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

      // Emphasis — bold weight only (system font, inherits body size); no
      // fontFamily so emoji inside bold text still render.
      strong: {
        fontWeight: "700" as const,
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
        fontWeight: "700" as const,
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
