"use client";

import "@opal/components/log/styles.css";
import { Section } from "@opal/layouts/general/components";
import { OverflowText } from "@opal/components/overflow-text/components";
import { Fold } from "@opal/components/fold/components";
import { Interactive } from "@opal/core";
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
  "default" | "info" | "success" | "warning" | "error"
>;

/** How much a line stands out: `heavy` adds a tinted background. */
type LogWeight = "heavy" | "light";

/**
 * A status and its weight, e.g. `"error-heavy"`. `default` has no weight: it
 * is never tinted.
 */
type LogVariant = "default" | `${Exclude<LogStatus, "default">}-${LogWeight}`;

type LogBaseProps = {
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
  /**
   * A button at the very end, such as a fold chevron. It sits outside the
   * inner 0.25rem the rest of the line has, so it is nearer the edge.
   */
  endButton?: React.ReactNode;
  /**
   * Makes the log interactive: the line and its body hover and press as one,
   * and a click anywhere on them, except on a link, calls this. A button
   * inside (e.g. a chevron) is its keyboard target; that button's click
   * reaches this too.
   */
  onClick?: () => void;
};

type LogExpandableProps =
  | { expandable?: false; expanded?: never; expandedContent?: never }
  | {
      /** Adds a body below the line that opens and closes. */
      expandable: true;
      /** Whether the body is open. Controlled: the caller owns the state. */
      expanded: boolean;
      /** The body, aligned under the title. */
      expandedContent: React.ReactNode;
    };

type LogProps = LogBaseProps & LogExpandableProps;

// The title is always text-03; `centerChildren` brings its own colour.
const VARIANTS: Record<LogVariant, { status: LogStatus; weight: LogWeight }> = {
  default: { status: "default", weight: "light" },
  "info-heavy": { status: "info", weight: "heavy" },
  "info-light": { status: "info", weight: "light" },
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
 * content, 2.25rem tall. The variant colours the icon; a heavy variant also
 * tints the line, and its body when expanded. A title too long for its column
 * shows in full in a tooltip.
 *
 * With `onClick`, the line is interactive. With `expandable`, a body opens
 * below it while `expanded`.
 */
function Log({
  variant = "default",
  icon: Icon,
  title,
  centerChildren,
  rightChildren,
  endButton,
  onClick,
  expandable,
  expanded,
  expandedContent,
}: LogProps) {
  const { status, weight } = VARIANTS[variant];

  const line = (
    <Section
      flexDirection="row"
      justifyContent="start"
      height={2.25}
      padding={1}
      gap={0}
      className="opal-log-line"
    >
      {/* Everything but `endButton` takes another 0.25rem, so the button
          sits nearer the edge with a larger hover area around it. */}
      <Section
        flexDirection="row"
        justifyContent="start"
        height="fit"
        padding={1}
        gap={1}
        className="min-w-0 flex-1"
      >
        <Section width="fit" height="fit" padding={0.5}>
          <Icon size={16} className="opal-log-icon" />
        </Section>

        {/* The title, the centre content and the trailing content sit 1rem
            apart, wider than the line's gap, so the columns read apart. */}
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

          {rightChildren}
        </Section>
      </Section>

      {endButton}
    </Section>
  );

  const body = expandable && (
    <Fold open={expanded}>
      <div className="opal-log-body">{expandedContent}</div>
    </Fold>
  );

  return (
    <div
      className="opal-log"
      data-opal-log-status={status}
      data-opal-log-weight={weight}
    >
      {onClick ? (
        // The whole log is one surface: the line and its body hover and
        // press together, and a click anywhere toggles it. A link inside
        // keeps its own click.
        <Interactive.Stateless
          variant="default"
          prominence="tertiary"
          onClick={(event: React.MouseEvent) => {
            if (event.target instanceof Element && event.target.closest("a")) {
              return;
            }
            onClick();
          }}
        >
          <Interactive.Container rounding={2} size="fit" width="full">
            {/* The container centres a flex child; this one fills it and may
                shrink, so the line truncates instead of overflowing. */}
            <div className="w-full min-w-0">
              {line}
              {body}
            </div>
          </Interactive.Container>
        </Interactive.Stateless>
      ) : (
        <>
          {line}
          {body}
        </>
      )}
    </div>
  );
}

export { Log, type LogProps, type LogStatus, type LogVariant, type LogWeight };
