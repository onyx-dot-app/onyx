"use client";

import "@opal/components/lines/line/styles.css";
import { Section } from "@opal/layouts/general/components";
import { Text } from "@opal/components/text/components";
import { Fold } from "@opal/components/fold/components";
import { Interactive } from "@opal/core";
import type { IconFunctionComponent, RichStr, StatusColor } from "@opal/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** The statuses a line can show. */
type LineStatus = Extract<
  StatusColor,
  "default" | "info" | "success" | "warning" | "error"
>;

/** How much a line stands out: `heavy` adds a tinted background. */
type LineWeight = "heavy" | "light";

/**
 * A status and its weight, e.g. `"error-heavy"`. `default` has no weight: it
 * is never tinted.
 */
type LineVariant =
  | "default"
  | `${Exclude<LineStatus, "default">}-${LineWeight}`;

type LineCommonProps = {
  /** Colours the icon; a heavy variant also tints the line and its body. */
  variant?: LineVariant;
  /**
   * The line's outer padding, as a spacing step (`N / 4` rem): `1` is
   * 0.25rem, `0` none, for a line inside a container that pads it already.
   * The line is 1.75rem tall plus this padding, and the body follows it.
   * @default 1
   */
  padding?: 0 | 1;
  /** Shown at 1rem, in the status colour. */
  icon: IconFunctionComponent;
  /**
   * Trailing content at the very end, such as a tag, actions or a fold
   * chevron. It sits outside the inner 0.25rem the rest of the line has, so a
   * button there is nearer the edge. Not padded.
   */
  rightChildren?: React.ReactNode;
  /**
   * Makes the line interactive: the line and its body hover and press as
   * one, and a click anywhere on them, except on a link, calls this. A button
   * inside (e.g. a chevron) is its keyboard target; that button's click
   * reaches this too.
   */
  onClick?: () => void;
};

type LineContentProps =
  | {
      /** What the line is about. Fills the row, on one line. */
      title: string | RichStr;
      children?: never;
    }
  | {
      /** A row of your own between the icon and `rightChildren`. */
      children: React.ReactNode;
      title?: never;
    };

type LineExpandableProps =
  | { expandable?: false; expanded?: never; expandedContent?: never }
  | {
      /** Adds a body below the line that opens and closes. */
      expandable: true;
      /** Whether the body is open. Controlled: the caller owns the state. */
      expanded: boolean;
      /** The body, aligned under the content. */
      expandedContent: React.ReactNode;
    };

type LineProps = LineCommonProps & LineContentProps & LineExpandableProps;

const VARIANTS: Record<
  LineVariant,
  { status: LineStatus; weight: LineWeight }
> = {
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
// Line
// ---------------------------------------------------------------------------

/**
 * One line of a list, a log or a timeline: an icon, a title (or a row of your
 * own) and trailing content, 1.75rem tall plus its padding. The variant
 * colours the icon; a heavy variant also tints the line, and its body when
 * expanded. A title too long for the row shows in full in a tooltip.
 *
 * With `onClick`, the line is interactive. With `expandable`, a body opens
 * below it while `expanded`.
 */
function Line({
  variant = "default",
  padding = 1,
  icon: Icon,
  title,
  children,
  rightChildren,
  onClick,
  expandable,
  expanded,
  expandedContent,
}: LineProps) {
  const { status, weight } = VARIANTS[variant];

  const line = (
    <Section
      flexDirection="row"
      justifyContent="start"
      // 1.75rem of content plus the padding on both sides.
      height={1.75 + (padding * 2) / 4}
      padding={padding}
      gap={0}
      className="opal-line-row"
    >
      {/* Everything but `rightChildren` takes another 0.25rem, so a button
          there sits nearer the edge with a larger hover area around it. */}
      <Section
        flexDirection="row"
        justifyContent="start"
        height="fit"
        padding={1}
        gap={1}
        className="min-w-0 flex-1"
      >
        <Section width="fit" height="fit" padding={0.5}>
          <Icon size={16} className="opal-line-icon" />
        </Section>

        {children ?? (
          <Section
            flexDirection="row"
            justifyContent="start"
            height="fit"
            className="min-w-0 flex-1"
          >
            <Text
              maxLines={1}
              overflowTooltip
              font="secondary-action"
              color="text-03"
            >
              {title}
            </Text>
          </Section>
        )}
      </Section>

      {rightChildren}
    </Section>
  );

  const body = expandable && (
    <Fold open={expanded}>
      <div className="opal-line-body">{expandedContent}</div>
    </Fold>
  );

  return (
    <div
      className="opal-line"
      data-opal-line-status={status}
      data-opal-line-weight={weight}
      data-opal-line-padding={padding}
    >
      {onClick ? (
        // The whole line is one surface: the line and its body hover and
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

export {
  Line,
  type LineProps,
  type LineCommonProps,
  type LineExpandableProps,
  type LineStatus,
  type LineVariant,
  type LineWeight,
};
