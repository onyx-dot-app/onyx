"use client";

import { Text } from "@opal/components";
import { getLanguageFromPath } from "@/app/craft/utils/codeLanguage";
import { useCodeHighlighter } from "@/app/craft/hooks/useCodeHighlighter";
import { getLanguageHint } from "@/app/craft/components/tool-cards/helpers";
import ToolCardSurface, {
  ToolCardSection,
  MONO_STYLE,
} from "@/app/craft/components/tool-cards/ToolCardSurface";
import type { ToolCardBodyProps } from "@/app/craft/components/tool-cards/interfaces";

/**
 * GenericBody - Fallback body for tools without a specialized renderer. Renders
 * the raw output as a monospace block in the shared surface, with syntax
 * highlighting when a language can be derived.
 */
export default function GenericBody({ toolCall }: ToolCardBodyProps) {
  const content = toolCall.rawOutput;
  const hint = getLanguageHint(toolCall);
  const lang = hint?.includes(".") ? getLanguageFromPath(hint) : hint;
  const highlight = useCodeHighlighter(!!content && !!lang);
  const html = content && lang && highlight ? highlight(content, lang) : null;

  return (
    <ToolCardSurface>
      <ToolCardSection className="whitespace-pre-wrap wrap-break-word">
        {content ? (
          html ? (
            <p
              style={MONO_STYLE}
              className="text-text-03 hljs"
              dangerouslySetInnerHTML={{ __html: html }}
            />
          ) : (
            <Text as="p" font="secondary-mono" color="text-03">
              {content}
            </Text>
          )
        ) : (
          <Text font="secondary-mono" color="text-02">
            No output yet...
          </Text>
        )}
      </ToolCardSection>
    </ToolCardSurface>
  );
}
