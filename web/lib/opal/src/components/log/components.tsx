"use client";

import "@opal/components/log/styles.css";
import { Section } from "@opal/layouts/general/components";
import { OverflowText } from "@opal/components/overflow-text/components";
import type {
  IconFunctionComponent,
  RichStr,
  StatusVariants,
} from "@opal/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** The statuses a log line can show. */
type LogStatus = Extract<
  StatusVariants,
  "default" | "success" | "warning" | "error"
>;

/** How much a line stands out: `heavy` adds a tinted background. */
type LogWeight = "heavy" | "light";

/**
 * A status and its weight, e.g. `"error-heavy"`. `default` has no weight: it
 * is never tinted.
 */
type LogVariant = "default" | `${Exclude<LogStatus, "default">}-${LogWeight}`;

interface LogProps {
  /** Colours the icon; a heavy variant also tints the line. */
  variant?: LogVariant;
  /** Shown at 1rem, in the status colour. */
  icon: IconFunctionComponent;
  /** What the line is about. One line, in a 10rem column. */
  title: string | RichStr;
  /**
   * What happened, filling the rest of the row from its start. Any content:
   * the caller sets its colour and how it fits on one line.
   */
  centerChildren?: React.ReactNode;
  /** Trailing content, such as a tag or an action. Not padded. */
  rightChildren?: React.ReactNode;
}

// The title is always text-03; `centerChildren` brings its own colour.
const VARIANTS: Record<LogVariant, { status: LogStatus; weight: LogWeight }> = {
  default: { status: "default", weight: "light" },
  "success-heavy": { status: "success", weight: "heavy" },
  "success-light": { status: "success", weight: "light" },
  "warning-heavy": { status: "warning", weight: "heavy" },
  "warning-light": { status: "warning", weight: "light" },
  "error-heavy": { status: "error", weight: "heavy" },
  "error-light": { status: "error", weight: "light" },
};

// ---------------------------------------------------------------------------
// Log
// ---------------------------------------------------------------------------

/**
 * One line of a log or report: an icon, a title, centre content and trailing
 * content, 2.25rem tall. Not interactive. The variant colours the icon; a
 * heavy variant also tints the line. A title too long for its column shows in
 * full in a tooltip.
 */
function Log({
  variant = "default",
  icon: Icon,
  title,
  centerChildren,
  rightChildren,
}: LogProps) {
  const { status, weight } = VARIANTS[variant];

  return (
    <Section
      flexDirection="row"
      justifyContent="start"
      height={2.25}
      padding={2}
      gap={1}
      className="opal-log"
      data-opal-log-status={status}
      data-opal-log-weight={weight}
    >
      <Section width="fit" height="fit" padding={0.5}>
        <Icon size={16} className="opal-log-icon" />
      </Section>

      {/* The title and the centre content sit 1rem apart, wider than the
          line's gap, so the title column reads as a label. */}
      <Section
        flexDirection="row"
        justifyContent="start"
        height="fit"
        gap={4}
        className="min-w-0 flex-1"
      >
        <Section
          flexDirection="row"
          justifyContent="start"
          width={10}
          height="fit"
          className="shrink-0"
        >
          <OverflowText font="secondary-action" color="text-03">
            {title}
          </OverflowText>
        </Section>

        <Section
          flexDirection="row"
          justifyContent="start"
          height="fit"
          className="min-w-0 flex-1"
        >
          {centerChildren}
        </Section>
      </Section>

      {rightChildren}
    </Section>
  );
}

export { Log, type LogProps, type LogStatus, type LogVariant, type LogWeight };
