"use client";

import "@opal/components/lines/line-base/styles.css";
import { Section } from "@opal/layouts/general/components";
import { Interactive } from "@opal/core";
import type { IconFunctionComponent, StatusColor } from "@opal/types";
import { CONTENT_STATUS_COLORS } from "@opal/layouts/content/colors";

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
  /** `card`: rounded and padded as a card, with a neutral fill. */
  flavour?: "step" | "card";
  /** Card only: fills it with `background-tint-00`. */
  filled?: boolean;
  /** Card only: a folded card fills on hover, since its header toggles it. */
  clickable?: boolean;
  children: React.ReactNode;
}

/** The line's frame: its rounding, status colours and heavy tint. */
function LineRoot({
  variant,
  padding,
  flavour = "step",
  filled = false,
  clickable = false,
  children,
}: LineRootProps) {
  const { status, weight } = VARIANTS[variant];
  // The status colour for the icon and the title (see styles.css).
  const style: React.CSSProperties & Record<"--opal-line-status-fg", string> = {
    "--opal-line-status-fg": CONTENT_STATUS_COLORS[status].fg,
  };
  return (
    <div
      className="opal-line"
      data-opal-line-status={status}
      data-opal-line-weight={weight}
      data-opal-line-padding={padding}
      style={style}
      data-opal-line-flavour={flavour}
      data-opal-line-filled={filled}
      data-opal-line-clickable={clickable}
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
// LineSurface
// ---------------------------------------------------------------------------

interface LineSurfaceProps {
  /**
   * Called on a click on the row. A click in the body, on a link, or one that
   * ends a text selection does not call it.
   */
  onClick: () => void;
  children: React.ReactNode;
}

/**
 * A `tertiary` stateless surface: the row and the body hover and press as
 * one, but only the row toggles. The body keeps its text selection, its
 * cursor and its own clicks.
 */
function LineSurface({ onClick, children }: LineSurfaceProps) {
  return (
    <Interactive.Stateless
      variant="default"
      prominence="tertiary"
      onClick={(event: React.MouseEvent) => {
        const target = event.target;
        if (target instanceof Element) {
          if (target.closest("a")) return;
          // This line's own body, not that of a line around it (a step
          // inside a card's body).
          const body = target.closest(".opal-line-body");
          if (body && event.currentTarget.contains(body)) return;
        }
        if (window.getSelection()?.toString()) return;
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
  LineRoot,
  LineRow,
  LineSurface,
  type LineBaseProps,
  type LineExpandableProps,
  type LineStatus,
  type LineVariant,
  type LineWeight,
};
