"use client";

import { Text } from "@opal/components";
import { useCodeHighlighter } from "@/app/craft/hooks/useCodeHighlighter";
import ToolCardSurface, {
  ToolCardSection,
  MONO_STYLE,
} from "@/app/craft/components/tool-cards/ToolCardSurface";
import type { ToolCardBodyProps } from "@/app/craft/components/tool-cards/interfaces";

/**
 * BashBody - command + stdout/stderr. The command sits in its own section with
 * a "$ " prefix and bash highlighting; the output sits in a divided, tinted
 * section below so the two read as distinct bands. Both use the same 12px
 * monospace size so the result never looks larger than the command.
 */
export default function BashBody({ toolCall }: ToolCardBodyProps) {
  const command = toolCall.command;
  const output = toolCall.rawOutput;
  const highlight = useCodeHighlighter(!!command);
  const commandHtml = command && highlight ? highlight(command, "bash") : null;

  return (
    <ToolCardSurface>
      {command && (
        <ToolCardSection>
          <p
            style={MONO_STYLE}
            className="text-text-04 whitespace-pre-wrap wrap-break-word hljs"
          >
            <span className="select-none text-text-02">{"$ "}</span>
            {commandHtml ? (
              <span dangerouslySetInnerHTML={{ __html: commandHtml }} />
            ) : (
              command
            )}
          </p>
        </ToolCardSection>
      )}
      {output && (
        <ToolCardSection
          divider={!!command}
          tinted={!!command}
          className="whitespace-pre-wrap wrap-break-word"
        >
          <Text as="p" font="secondary-mono" color="text-03">
            {output}
          </Text>
        </ToolCardSection>
      )}
      {!command && !output && (
        <ToolCardSection>
          <Text font="secondary-mono" color="text-03">
            No output
          </Text>
        </ToolCardSection>
      )}
    </ToolCardSurface>
  );
}
