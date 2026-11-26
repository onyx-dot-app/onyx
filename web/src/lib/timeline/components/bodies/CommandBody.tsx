"use client";

import React from "react";
import { useTranslations } from "next-intl";
import { CodePanel, type CodePanelLine } from "@opal/components";
import { useCodeLines } from "@/lib/timeline/components/bodies/useCodeLines";
import type { RichNodes, RichStr } from "@opal/types";
import { stripBidiControls } from "@opal/utils";

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
  /**
   * `command` is a patch: each file shows under its own header (its path),
   * with `+` and `-` lines as added and removed lines with markers.
   */
  diff?: boolean;
}

interface PatchFile {
  /** The file's path, and its new path when it moved. */
  path: string;
  lines: CodePanelLine[];
}

/**
 * A patch split by file, each file's lines as diff lines. A hunk header with
 * context becomes a note; a bare `@@` is dropped.
 */
/** The most patch lines shown; the rest is a note, and copy keeps all. */
const MAX_PATCH_LINES = 2000;

/** A heredoc wrapper around a patch (`<<EOF` … `EOF`), as the tool accepts. */
const HEREDOC_OPEN = /^<<['"]?(\w+)['"]?\s*$/;

function patchFiles(
  patch: string,
  moreLines: (count: number) => string
): PatchFile[] {
  const files: PatchFile[] = [];
  let file: PatchFile | null = null;
  let lines = patch.split(/\r?\n/);
  // Strip a heredoc wrapper, so its lines do not show as a file.
  const opener = HEREDOC_OPEN.exec(lines[0]?.trim() ?? "");
  if (opener) {
    const closing = lines.findLastIndex((line) => line.trim() === opener[1]);
    lines = lines.slice(1, closing > 0 ? closing : undefined);
  }
  let shown = 0;
  for (const line of lines) {
    if (shown >= MAX_PATCH_LINES) {
      if (file !== null) {
        file.lines.push({
          kind: "note",
          content: moreLines(lines.length - shown),
        });
      }
      break;
    }
    shown++;
    if (line === "*** Begin Patch" || line === "*** End Patch") continue;
    const header = line.match(/^\*\*\* (?:Add|Update|Delete) File: (.*)$/);
    if (header || file === null) {
      file = { path: header?.[1] ?? "", lines: [] };
      files.push(file);
      if (header) continue;
    }
    if (line.startsWith("*** Move to: ")) {
      file.path = `${file.path} → ${line.slice(13)}`;
    } else if (line.startsWith("@@")) {
      const context = line.slice(2).trim();
      if (context) file.lines.push({ kind: "note", content: context });
    } else if (line.startsWith("+")) {
      file.lines.push({ kind: "added", content: line.slice(1) });
    } else if (line.startsWith("-")) {
      file.lines.push({ kind: "removed", content: line.slice(1) });
    } else {
      file.lines.push({ content: line.startsWith(" ") ? line.slice(1) : line });
    }
  }
  return files;
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
  diff = false,
}: CommandBodyProps) {
  // A cut patch says how many lines it left out, as a file preview does.
  const tRead = useTranslations("craft.toolCards.read");
  const commentLine = comment ? `# ${comment}` : null;
  const codeLines = useCodeLines(
    diff ? "" : commentLine ? `${commentLine}\n${command}` : command,
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
      {command &&
        (diff ? (
          // Each file under its own header: its path, then its diff lines.
          patchFiles(command, (count) =>
            tRead("moreLines.label", { count })
          ).map((file, index) => (
            <React.Fragment key={index}>
              <CodePanel.Header
                title={stripBidiControls(file.path) || title || ""}
                copyText={index === 0 ? command : undefined}
              />
              <CodePanel.Lines lines={file.lines} markers />
            </React.Fragment>
          ))
        ) : (
          <>
            {title && <CodePanel.Header title={title} copyText={command} />}
            <CodePanel.Lines lines={lines} lineNumbers={!prompt} />
          </>
        ))}
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
