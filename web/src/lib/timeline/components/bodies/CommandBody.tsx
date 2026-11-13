"use client";

import { Text } from "@opal/components";
import { useCodeHighlighter } from "@/app/craft/hooks/useCodeHighlighter";
import ToolCardSurface, {
  ToolCardSection,
  MONO_STYLE,
} from "@/lib/timeline/components/bodies/ToolCardSurface";

interface CommandBodyProps {
  /** The command or code that ran. */
  command: string;
  /** Highlighting language for the command. */
  language: "bash" | "python";
  /** Shown before a shell command, such as "$ ". */
  prompt?: string;
  output: string;
  /** Error output, shown in its own band. */
  error?: string;
  /** Shown when there is no command, output or error. */
  emptyLabel: string;
}

/**
 * The body of an execute step: the command in its own highlighted band, the
 * output in a divided, tinted band below, and error output last. Shared by
 * chat and Craft.
 */
export function CommandBody({
  command,
  language,
  prompt,
  output,
  error,
  emptyLabel,
}: CommandBodyProps) {
  const highlight = useCodeHighlighter(!!command);
  const commandHtml =
    command && highlight ? highlight(command, language) : null;

  return (
    <ToolCardSurface>
      {command && (
        <ToolCardSection>
          <p
            style={MONO_STYLE}
            className="text-text-04 whitespace-pre-wrap wrap-break-word hljs"
          >
            {prompt && (
              <span className="select-none text-text-02">{prompt}</span>
            )}
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
      {error && (
        <ToolCardSection
          divider={!!command || !!output}
          className="whitespace-pre-wrap wrap-break-word bg-status-error-01"
        >
          <Text as="p" font="secondary-mono" color="status-error-05">
            {error}
          </Text>
        </ToolCardSection>
      )}
      {!command && !output && !error && (
        <ToolCardSection>
          <Text font="secondary-mono" color="text-03">
            {emptyLabel}
          </Text>
        </ToolCardSection>
      )}
    </ToolCardSurface>
  );
}
