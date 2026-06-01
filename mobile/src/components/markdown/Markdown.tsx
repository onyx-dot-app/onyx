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

// "muted"/"muted-collapsed" mirror web mutedText/collapsedMarkdownComponents.
type MarkdownVariant = "default" | "muted" | "muted-collapsed";

interface MarkdownProps {
  children: string;
  variant?: MarkdownVariant;
  // citation_num -> document_id; when set, inline [[N]](url) become pills.
  citations?: CitationMap;
  documents?: OnyxDocument[] | null;
}

// Strip the trailing newline the parser appends to code blocks.
function trimTrailingNewline(content: string): string {
  if (content.length > 0 && content.charAt(content.length - 1) === "\n") {
    return content.substring(0, content.length - 1);
  }
  return content;
}

// Emoji render as "?" on the iOS 26 simulator only — RN CoreText bug
// facebook/react-native#56183 (all fonts, real devices unaffected). Not this
// renderer or the brand font, and there's no JS workaround.

// markdown-it stores the fence info string on node.sourceInfo.
function extractLanguage(node: ASTNode): string | undefined {
  const sourceInfo = (node as ASTNode & { sourceInfo?: string }).sourceInfo;
  if (typeof sourceInfo === "string" && sourceInfo.trim().length > 0) {
    // info strings can carry extra metadata after the language token.
    const lang = sourceInfo.trim().split(/\s+/)[0];
    return lang && lang.length > 0 ? lang : undefined;
  }
  return undefined;
}

// Native mirror of web MinimalMarkdown (GFM + code blocks with copy). Syntax
// highlighting (web: rehype-highlight) and KaTeX math (remark-math) aren't
// implemented — code is flat monospace and `$...$` renders as plain text.
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

  // Text-bearing styles cascade onto descendant text nodes via the library's
  // inheritedStyles mechanism, so `body` propagates to paragraphs/list items.
  const styles = useMemo(
    () => ({
      body: {
        ...typography["main-content-body"],
        color: bodyColor,
      },

      // Raw Opal heading-h1 is a 48px hero size, far too large in a chat
      // answer, so size + letterSpacing are overridden per heading.
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

      // Wrapper View only; text color cascades from body.
      paragraph: {
        marginTop: 0,
        marginBottom: paragraphSpacing,
        flexWrap: "wrap" as const,
        flexDirection: "row" as const,
        alignItems: "center" as const,
        justifyContent: "flex-start" as const,
        width: "100%" as const,
      },

      strong: {
        ...typography["main-content-emphasis"],
      },
      em: {
        fontStyle: "italic" as const,
      },
      s: {
        textDecorationLine: "line-through" as const,
      },

      link: {
        color: colors["action-text-link-05"],
        textDecorationLine: "underline" as const,
      },

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

      blockquote: {
        backgroundColor: colors["background-tint-02"],
        borderColor: colors["border-02"],
        borderLeftWidth: 4,
        borderRadius: radii["04"],
        marginVertical: 8,
        paddingHorizontal: 12,
        paddingVertical: 4,
      },

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

      hr: {
        backgroundColor: colors["border-01"],
        height: 1,
        marginVertical: 12,
      },

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

  // Override code-block rules with CodeBlock (copy button); when citations are
  // present, override `link` so [[N]](url) markers render as CitationPills.
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
    // Library style typing is stricter than our token-driven literal map; the
    // runtime accepts it fine, so cast for the style prop.
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
