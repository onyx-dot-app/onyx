// citationRule.tsx — a markdown-display `link` render rule that turns citation
// markers into pills. NOT a port of web's react-markdown anchor (different
// engine); authored for @ronradtke/react-native-markdown-display (markdown-it).
//
// markdown-it parses `[[N]](url)` into a link node whose child text node is
// `[N]` (verified empirically). We read node.children[0].content, match
// /^\[(D|Q)?\s*(\d+)\]$/, resolve the document via citations[n] -> document_id
// -> documents.find, and render a CitationPill. Unresolved (data still
// streaming) -> render nothing (web "unresolved-hidden"). [Q n] (sub-question)
// -> a non-interactive number chip. Non-citation links fall through to a normal
// pressable link.

import { Pressable, Text, Linking, type TextStyle } from "react-native";
import type { ASTNode } from "@ronradtke/react-native-markdown-display";

import type { CitationMap, OnyxDocument } from "@/lib/types";
import { CitationPill } from "@/components/message/citations/CitationPill";
import {
  documentToSourceInfo,
  getDisplayNameForSource,
} from "@/components/message/sources/sourceInfo";

export interface CitationRuleOptions {
  citations?: CitationMap;
  documents?: OnyxDocument[] | null;
}

const MARKER_RE = /^\[(D|Q)?\s*(\d+)\]$/;

export function makeCitationLinkRule(opts: CitationRuleOptions) {
  return function linkRule(
    node: ASTNode,
    children: React.ReactNode,
    _parent: ASTNode[],
    styles: { link?: TextStyle }
  ): React.ReactNode {
    const markerText = (node.children?.[0] as { content?: string } | undefined)
      ?.content;
    const match =
      typeof markerText === "string" ? markerText.match(MARKER_RE) : null;

    if (match) {
      const isQuestion = match[1] === "Q";
      const num = parseInt(match[2] ?? "0", 10);

      if (isQuestion) {
        // Sub-question citation: no sub-question UI on mobile -> static chip.
        return (
          <CitationPill key={node.key} label={String(num)} interactive={false} />
        );
      }

      const docId = opts.citations?.[num];
      const doc = docId
        ? opts.documents?.find((d) => d.document_id === docId)
        : undefined;

      // Unresolved while streaming -> hide the raw marker (matches web).
      if (!doc) return null;

      return (
        <CitationPill
          key={node.key}
          label={getDisplayNameForSource(doc)}
          sources={[documentToSourceInfo(doc)]}
        />
      );
    }

    // Non-citation link: open externally.
    const href = (node.attributes as { href?: string } | undefined)?.href;
    return (
      <Pressable
        key={node.key}
        accessibilityRole="link"
        onPress={() => {
          if (href) void Linking.openURL(href);
        }}
      >
        <Text style={styles.link}>{children}</Text>
      </Pressable>
    );
  };
}
