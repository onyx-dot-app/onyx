"use client";

import "@opal/components/code-panel/styles.css";
import { Hoverable } from "@opal/core";
import { Section } from "@opal/layouts";
import { Text } from "@opal/components/text/components";
import { CopyButton } from "@opal/components/buttons/copy-button/components";
import type { RichStr } from "@opal/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * A line's role. `context` is plain code; `added` and `removed` are diff
 * lines, tinted and marked `+` / `-`; `note` is a full-width line such as
 * "12 unchanged lines".
 */
type CodePanelLineKind = "context" | "added" | "removed" | "note";

interface CodePanelLine {
  /** The line: plain text, or highlighted markup. */
  content: React.ReactNode;
  /** Shown in the gutter when the lines show numbers. */
  number?: number;
  /** @default "context" */
  kind?: CodePanelLineKind;
}

interface CodePanelProps {
  /** The panel's parts, top to bottom: a header, lines, output, a footer. */
  children: React.ReactNode;
}

interface CodePanelHeaderProps {
  /** What the panel shows, such as a file path or a language. */
  title: string | RichStr;
  /** Controls before the copy button, such as stats or a view toggle. */
  rightChildren?: React.ReactNode;
  /** Adds a copy button at the end of the row, which copies this text. */
  copyText?: string;
}

interface CodePanelLinesProps {
  lines: CodePanelLine[];
  /** Shows each line's `number` in a gutter. @default false */
  lineNumbers?: boolean;
  /** Shows a `+` / `-` column for diff lines. @default false */
  markers?: boolean;
  /**
   * Adds a copy button that appears on hover at the top end, which copies
   * this text. For a panel without a header; a header has its own.
   */
  copyText?: string;
}

interface CodePanelColumnsProps {
  /** Two `CodePanel.Lines`, side by side, e.g. a split diff. */
  children: React.ReactNode;
}

interface CodePanelOutputProps {
  /** The output text. */
  children: string;
  /** Error output: red text on a red tint. @default false */
  error?: boolean;
}

interface CodePanelContentProps {
  /** Any content, such as links or a progress indicator. */
  children: React.ReactNode;
}

interface CodePanelFooterProps {
  title: string | RichStr;
  /** Controls at the end of the row, such as "Show all". */
  rightChildren?: React.ReactNode;
}

// ---------------------------------------------------------------------------
// Parts
// ---------------------------------------------------------------------------

/**
 * A bordered panel for code: an optional title row, lines with optional
 * numbers and diff markers, output, and a footer. Each part after the first
 * draws a divider above itself.
 */
function CodePanelRoot({ children }: CodePanelProps) {
  return <div className="opal-code-panel">{children}</div>;
}

/** The title row: a title, controls, and an optional copy button. */
function CodePanelHeader({
  title,
  rightChildren,
  copyText,
}: CodePanelHeaderProps) {
  return (
    <div className="opal-code-panel-header">
      <Section
        flexDirection="row"
        justifyContent="between"
        height="fit"
        gap={2}
      >
        <div className="opal-code-panel-title">
          <Text
            font="secondary-mono"
            color="text-03"
            maxLines={1}
            overflowTooltip
          >
            {title}
          </Text>
        </div>
        {(rightChildren || copyText !== undefined) && (
          <Section flexDirection="row" width="fit" height="fit" gap={1}>
            {rightChildren}
            {copyText !== undefined && (
              <CopyButton
                getCopyText={() => copyText}
                size="2xs"
                prominence="tertiary"
              />
            )}
          </Section>
        )}
      </Section>
    </div>
  );
}

const MARKERS: Record<CodePanelLineKind, string> = {
  context: " ",
  added: "+",
  removed: "-",
  note: "",
};

/** The code, one row per line, scrolling past 24rem. */
function CodePanelLines({
  lines,
  lineNumbers = false,
  markers = false,
  copyText,
}: CodePanelLinesProps) {
  const columns = 1 + (lineNumbers ? 1 : 0) + (markers ? 1 : 0);
  const table = (
    <div className="opal-code-panel-lines">
      <table>
        <tbody>
          {lines.map((line, index) => {
            const kind = line.kind ?? "context";
            return (
              <tr key={index} data-kind={kind}>
                {kind === "note" ? (
                  <td colSpan={columns} className="opal-code-panel-note">
                    {line.content}
                  </td>
                ) : (
                  <>
                    {lineNumbers && (
                      <td className="opal-code-panel-number">
                        {line.number ?? ""}
                      </td>
                    )}
                    {markers && (
                      <td className="opal-code-panel-marker">
                        {MARKERS[kind]}
                      </td>
                    )}
                    <td className="opal-code-panel-code">
                      {line.content === "" ? " " : line.content}
                    </td>
                  </>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );

  if (copyText === undefined) return table;
  return (
    <Hoverable.Root group="code-panel">
      <div className="opal-code-panel-copyable">
        {table}
        <Hoverable.Item group="code-panel">
          <div className="opal-code-panel-copy">
            <CopyButton
              getCopyText={() => copyText}
              size="2xs"
              prominence="tertiary"
            />
          </div>
        </Hoverable.Item>
      </div>
    </Hoverable.Root>
  );
}

/** Two sets of lines side by side, scrolling together. */
function CodePanelColumns({ children }: CodePanelColumnsProps) {
  return <div className="opal-code-panel-columns">{children}</div>;
}

/** Output under the code, or error output. */
function CodePanelOutput({ children, error = false }: CodePanelOutputProps) {
  return (
    <div className="opal-code-panel-output" data-error={error}>
      <Text
        as="p"
        font="secondary-mono"
        color={error ? "status-error-05" : "text-03"}
      >
        {children}
      </Text>
    </div>
  );
}

/** A padded row for content that is not code or output, such as links. */
function CodePanelContent({ children }: CodePanelContentProps) {
  return <div className="opal-code-panel-content">{children}</div>;
}

/** A closing row, such as "12 more lines" and a button to show them. */
function CodePanelFooter({ title, rightChildren }: CodePanelFooterProps) {
  return (
    <div className="opal-code-panel-footer">
      <Section
        flexDirection="row"
        justifyContent="between"
        height="fit"
        gap={2}
      >
        <Text font="secondary-body" color="text-02">
          {title}
        </Text>
        {rightChildren}
      </Section>
    </div>
  );
}

const CodePanel = Object.assign(CodePanelRoot, {
  Header: CodePanelHeader,
  Lines: CodePanelLines,
  Columns: CodePanelColumns,
  Output: CodePanelOutput,
  Content: CodePanelContent,
  Footer: CodePanelFooter,
});

export {
  CodePanel,
  type CodePanelProps,
  type CodePanelHeaderProps,
  type CodePanelLinesProps,
  type CodePanelColumnsProps,
  type CodePanelOutputProps,
  type CodePanelContentProps,
  type CodePanelFooterProps,
  type CodePanelLine,
  type CodePanelLineKind,
};
