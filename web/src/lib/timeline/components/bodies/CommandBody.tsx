"use client";

import { CodePanel } from "@opal/components";
import { useCodeLines } from "@/lib/timeline/components/bodies/useCodeLines";
import type { RichStr } from "@opal/types";

interface CommandBodyProps {
  /** The command or code that ran. */
  command: string;
  /** Highlighting language for the command; the title by default. */
  language?: "bash" | "python";
  /** The panel's title, such as the tool's name. Defaults to `language`. */
  title?: string;
  /** Shown before a shell command, such as "$ ". */
  prompt?: string;
  output: string;
  /** Error output, shown in its own band. */
  error?: string;
  /** Shown when there is no command, output or error. */
  emptyLabel: string;
  /** A closing line under the output, such as "Exit code 2". */
  footer?: string | RichStr;
}

/**
 * The body of an execute or search step, as an Opal `CodePanel`: a title row
 * with the language (or a title) and a copy button, the command (numbered, unless it has a shell
 * prompt), then its output and error output. Shared by chat and Craft.
 */
export function CommandBody({
  command,
  language,
  title = language,
  prompt,
  output,
  error,
  emptyLabel,
  footer,
}: CommandBodyProps) {
  const codeLines = useCodeLines(command, language);
  // A shell prompt leads the first line, in place of line numbers.
  const lines = prompt
    ? codeLines.map((line, index) =>
        index === 0
          ? {
              ...line,
              content: (
                <>
                  <span className="select-none text-text-02">{prompt}</span>
                  {line.content}
                </>
              ),
            }
          : line
      )
    : codeLines;

  return (
    <CodePanel>
      {command && (
        <>
          {title && <CodePanel.Header title={title} copyText={command} />}
          <CodePanel.Lines lines={lines} lineNumbers={!prompt} />
        </>
      )}
      {output && <CodePanel.Output>{output}</CodePanel.Output>}
      {error && <CodePanel.Output error>{error}</CodePanel.Output>}
      {!command && !output && !error && (
        <CodePanel.Output>{emptyLabel}</CodePanel.Output>
      )}
      {footer && <CodePanel.Footer title={footer} />}
    </CodePanel>
  );
}
