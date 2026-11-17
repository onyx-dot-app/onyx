"use client";

import { cn } from "@opal/utils";
import { Section } from "@opal/layouts/general/components";
import { Text } from "@opal/components/text/components";
import {
  LineBody,
  LineRoot,
  LineRow,
  type LineBaseProps,
  type LineExpandableProps,
} from "@opal/components/lines/line-base/components";
import type { RichStr } from "@opal/types";

type LineStepProps = LineBaseProps &
  LineExpandableProps & {
    /** One line of a list or a timeline. */
    flavour?: "step";
    /** What the line is about. Fills the row, on one line. */
    title: string | RichStr;
    /**
     * Makes the row toggle the line: a click on it, except on a link, calls
     * this, and hovering it darkens its title and icon (no fill). The body
     * never calls this. A button in `rightChildren` (e.g. a chevron) is its
     * keyboard target; that button's click reaches this too.
     */
    onClick?: () => void;
  };

type LineCardProps = LineExpandableProps & {
  /** A card: any header, trailing controls and a body below. */
  flavour: "card";
  /** The header: any content, such as a title that animates. */
  children: React.ReactNode;
  /** Trailing content at the end of the header, such as the fold button. */
  rightChildren?: React.ReactNode;
  /** Fills the card with `background-tint-00`, e.g. while it is open. */
  filled: boolean;
  /**
   * Makes the header toggle the card: a click anywhere on it calls this, and
   * a folded card fills on hover. A button in `rightChildren` is its keyboard
   * target; that button's click reaches this too.
   */
  onClick?: () => void;
};

type LineProps = LineStepProps | LineCardProps;

/**
 * One line of a list or a timeline: an icon, a title and trailing content,
 * 1.75rem tall plus its padding. The variant colours the icon; a heavy
 * variant also tints the line, and its body when expanded. A title too long
 * for the row shows in full in a tooltip.
 *
 * With `onClick`, the row toggles the line and hovers subtly; the body keeps
 * its own clicks and selection. With `expandable`, a body opens below the
 * row while `expanded`.
 */
function LineStep({
  variant = "default",
  padding = 1,
  icon,
  title,
  rightChildren,
  onClick,
  expandable,
  expanded,
  expandedContent,
}: LineStepProps) {
  const row = (
    <LineRow padding={padding} icon={icon} rightChildren={rightChildren}>
      <Section
        flexDirection="row"
        justifyContent="start"
        height="fit"
        className="min-w-0 flex-1"
      >
        <span className="opal-line-title">
          <Text
            maxLines={1}
            overflowTooltip
            font="secondary-action"
            color="inherit"
          >
            {title}
          </Text>
        </span>
      </Section>
    </LineRow>
  );

  return (
    <LineRoot variant={variant} padding={padding}>
      {onClick ? (
        // The row toggles the line and hovers subtly: its title and icon
        // darken, with no fill, so the body needs no gap to keep off it.
        <div
          role="presentation"
          className="opal-line-toggle"
          onClick={(event: React.MouseEvent) => {
            if (event.target instanceof Element && event.target.closest("a")) {
              return;
            }
            onClick();
          }}
        >
          {row}
        </div>
      ) : (
        row
      )}
      {expandable && (
        <LineBody expanded={expanded} inset="content">
          {expandedContent}
        </LineBody>
      )}
    </LineRoot>
  );
}

// ---------------------------------------------------------------------------
// Card
// ---------------------------------------------------------------------------

function LineCard({
  children,
  rightChildren,
  filled,
  onClick,
  expandable,
  expanded,
  expandedContent,
}: LineCardProps) {
  return (
    <LineRoot
      variant="default"
      padding={0}
      flavour="card"
      filled={filled}
      clickable={!!onClick && !filled}
    >
      <div
        role="presentation"
        className={cn(onClick && "cursor-pointer select-none")}
        onClick={onClick}
      >
        <Section flexDirection="row" justifyContent="between" height="fit">
          <div className="min-w-0 flex-1">{children}</div>
          {rightChildren}
        </Section>
      </div>
      {expandable && (
        <LineBody expanded={expanded} inset="top">
          {expandedContent}
        </LineBody>
      )}
    </LineRoot>
  );
}

/**
 * A line in one of two flavours. `step` (the default): one line of a list or
 * a timeline, an icon, a title and trailing content. `card`: a run card, any
 * header with trailing controls, the steps in its body, and a neutral fill.
 */
function Line(props: LineProps) {
  return props.flavour === "card" ? (
    <LineCard {...props} />
  ) : (
    <LineStep {...props} />
  );
}

export { Line, type LineProps };
