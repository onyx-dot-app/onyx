"use client";

import { CodePanel, type CodePanelLine } from "@opal/components";
import { useCodeHighlighter } from "@/app/craft/hooks/useCodeHighlighter";

interface CommandBodyProps {
  /** The command or code that ran. */
  command: string;
  /** Highlighting language for the command; also the panel's title. */
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
 * The body of an execute step, as an Opal `CodePanel`: a title row with the
 * language and a copy button, the command (numbered, unless it has a shell
 * prompt), then its output and error output. Shared by chat and Craft.
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

  const lines: CodePanelLine[] = command.split("\n").map((line, index) => {
    const html = highlight ? highlight(line, language) : null;
    return {
      number: index + 1,
      content: (
        <>
          {prompt && index === 0 && (
            <span className="select-none text-text-02">{prompt}</span>
          )}
          {html !== null ? (
            <span dangerouslySetInnerHTML={{ __html: html }} />
          ) : (
            line
          )}
        </>
      ),
    };
  });

  return (
    <CodePanel>
      {command && (
        <>
          <CodePanel.Header title={language} copyText={command} />
          <CodePanel.Lines lines={lines} lineNumbers={!prompt} />
        </>
      )}
      {output && <CodePanel.Output>{output}</CodePanel.Output>}
      {error && <CodePanel.Output error>{error}</CodePanel.Output>}
      {!command && !output && !error && (
        <CodePanel.Output>{emptyLabel}</CodePanel.Output>
      )}
    </CodePanel>
  );
}
