"use client";

import "@opal/components/cards/line-base/styles.css";
import { Section } from "@opal/layouts/general/components";
import { Fold } from "@opal/components/fold/components";
import { Interactive } from "@opal/core";
import type { IconFunctionComponent, StatusColor } from "@opal/types";

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

/** The props every line shares: `Line` and `Log`. */
type LineBaseProps = {
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
// LineRoot
// ---------------------------------------------------------------------------

interface LineRootProps {
  variant: LineVariant;
  padding: 0 | 1;
  children: React.ReactNode;
}

/** The line's frame: its rounding, status colours and heavy tint. */
function LineRoot({ variant, padding, children }: LineRootProps) {
  const { status, weight } = VARIANTS[variant];
  return (
    <div
      className="opal-line"
      data-opal-line-status={status}
      data-opal-line-weight={weight}
      data-opal-line-padding={padding}
    >
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// LineRow
// ---------------------------------------------------------------------------

interface LineRowProps {
  padding: 0 | 1;
  icon: IconFunctionComponent;
  rightChildren?: React.ReactNode;
  /** The content between the icon and `rightChildren`. */
  children: React.ReactNode;
}

/** The line itself: the icon, the content and the trailing content. */
function LineRow({
  padding,
  icon: Icon,
  rightChildren,
  children,
}: LineRowProps) {
  return (
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
        {children}
      </Section>

      {rightChildren}
    </Section>
  );
}

// ---------------------------------------------------------------------------
// LineBody
// ---------------------------------------------------------------------------

interface LineBodyProps {
  expanded: boolean;
  /**
   * Where the body is padded. `around`: on the start, end and bottom, the
   * line's padding. `start`: only on the start, to sit under the content,
   * and 0.25rem on the top, inside the fold, to space it from the row.
   * @default "around"
   */
  inset?: "around" | "start";
  children: React.ReactNode;
}

/** The body that opens below the line, indented to start under the content. */
function LineBody({ expanded, inset = "around", children }: LineBodyProps) {
  return (
    <Fold open={expanded}>
      <div className="opal-line-body" data-opal-line-body-inset={inset}>
        {children}
      </div>
    </Fold>
  );
}

// ---------------------------------------------------------------------------
// LineSurface
// ---------------------------------------------------------------------------

interface LineSurfaceProps {
  /** Called on a click anywhere in the surface, except on a link. */
  onClick: () => void;
  children: React.ReactNode;
}

/** A `tertiary` stateless surface that hovers, presses and clicks as one. */
function LineSurface({ onClick, children }: LineSurfaceProps) {
  return (
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
        <div className="w-full min-w-0">{children}</div>
      </Interactive.Container>
    </Interactive.Stateless>
  );
}

export {
  LineBody,
  LineRoot,
  LineRow,
  LineSurface,
  type LineBaseProps,
  type LineExpandableProps,
  type LineStatus,
  type LineVariant,
  type LineWeight,
};
