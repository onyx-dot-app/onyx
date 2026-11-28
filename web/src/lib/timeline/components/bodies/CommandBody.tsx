"use client";

import { CodePanel } from "@opal/components";
import { useCodeLines } from "@/lib/timeline/components/bodies/useCodeLines";
import type { RichNodes, RichStr } from "@opal/types";

interface CommandBodyProps {
  /** The command or code that ran. */
  command: string;
  /** Highlighting language for the command; the title by default. */
  language?: "bash" | "python";
  /** The panel's title, such as the tool's name. Defaults to `language`. */
  title?: string;
  /** Shown before a shell command, such as "$ ". */
  prompt?: string;
  /** A comment line above the command, such as "in /workspace/app"; it is
   *  highlighted as a comment and not copied. */
  comment?: string;
  /** Plain text, or styled nodes such as terminal colors. */
  output: string | RichNodes;
  /** Error output, shown in its own band. */
  error?: string;
  /** Shown when there is no command, output or error. */
  emptyLabel: string;
  /** A closing line under the output, such as "Exit code 2". */
  footer?: string | RichStr;
  /** The command runs and has no output yet: the output panel shows a
   *  loading shimmer. */
  outputLoading?: boolean;
  /** The output still streams: keep its newest lines in view. */
  outputFollow?: boolean;
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
  comment,
  output,
  error,
  emptyLabel,
  footer,
  outputLoading = false,
  outputFollow = false,
}: CommandBodyProps) {
  const commentLine = comment ? `# ${comment}` : null;
  const codeLines = useCodeLines(
    commentLine ? `${commentLine}\n${command}` : command,
    language
  );
  // A shell prompt leads the command's first line (after any comment), in
  // place of line numbers.
  const promptLine = commentLine ? 1 : 0;
  const lines = prompt
    ? codeLines.map((line, index) =>
        index === promptLine
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
      {output && (
        <CodePanel.Output follow={outputFollow}>{output}</CodePanel.Output>
      )}
      {error && <CodePanel.Output error>{error}</CodePanel.Output>}
      {outputLoading && !output && !error && <CodePanel.Output loading />}
      {!command && !output && !error && !outputLoading && (
        <CodePanel.Output>{emptyLabel}</CodePanel.Output>
      )}
      {footer && <CodePanel.Footer title={footer} />}
    </CodePanel>
  );
}
