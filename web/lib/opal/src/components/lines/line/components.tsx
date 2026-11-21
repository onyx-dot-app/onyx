"use client";

import { Section } from "@opal/layouts/general/components";
import { Text } from "@opal/components/text/components";
import { Collapsible } from "@opal/components/collapsible/components";
import { Presence } from "@opal/components/presence/components";
import {
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
     * The title's identity. A new key swaps the title through an animation;
     * a new title with the same key updates in place, so a live title that
     * changes often does not flash. Defaults to the title's text.
     */
    titleKey?: React.Key;
    /**
     * Makes the row toggle the line, as a `Collapsible.Header` with a chevron
     * fold button: a click on the row calls this, and hovering it darkens
     * its title and icon (no fill). The body never calls this. Controls in
     * `rightChildren` keep their own clicks.
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
   * The fold button's label, e.g. "3 steps": the header's own button, which
   * lights up while the header is hovered. Needs `onClick`.
   */
  foldLabel?: string;
  /**
   * Makes the header toggle the card: a click on it, or on its fold button,
   * calls this, and a folded card fills on hover.
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
  titleKey,
  rightChildren,
  onClick,
  expandable,
  expanded,
  expandedContent,
}: LineStepProps) {
  const content = (
    <Section
      flexDirection="row"
      justifyContent="start"
      height="fit"
      className="min-w-0 flex-1"
    >
      <span className="opal-line-title">
        {/* A new title key (e.g. "Searching" to "Searched") swaps; it never
            flashes. */}
        <Presence.Swap
          swapKey={titleKey ?? (typeof title === "string" ? title : title.raw)}
        >
          <Text
            maxLines={1}
            overflowTooltip
            font="secondary-action"
            color="inherit"
          >
            {title}
          </Text>
        </Presence.Swap>
      </span>
    </Section>
  );

  if (!expandable && !onClick) {
    return (
      <LineRoot variant={variant} padding={padding}>
        <LineRow padding={padding} icon={icon} rightChildren={rightChildren}>
          {content}
        </LineRow>
      </LineRoot>
    );
  }

  return (
    <LineRoot variant={variant} padding={padding}>
      <Collapsible.Root
        open={!!expandable && expanded}
        onOpenChange={() => onClick?.()}
      >
        {onClick ? (
          // The row toggles the line and hovers subtly: its title and icon
          // darken, with no fill. The chevron is the keyboard control.
          <Collapsible.Header
            name={title}
            rightChildren={rightChildren}
            size="md"
            foldButton="chevron"
            hover="subtle"
          >
            <LineRow padding={padding} icon={icon}>
              {content}
            </LineRow>
          </Collapsible.Header>
        ) : (
          <LineRow padding={padding} icon={icon} rightChildren={rightChildren}>
            {content}
          </LineRow>
        )}
        {expandable && (
          <Collapsible.Content>
            <div className="opal-line-body" data-opal-line-body-inset="content">
              {expandedContent}
            </div>
          </Collapsible.Content>
        )}
      </Collapsible.Root>
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
  foldLabel,
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
      <Collapsible.Root
        open={!!expandable && expanded}
        onOpenChange={() => onClick?.()}
        // A card without `onClick` (e.g. a run with no steps yet) cannot fold.
        disabled={!onClick}
      >
        {/* Always the same header, foldable or not, so the header's content
            (e.g. a title in Presence.Swap) keeps its place when the card
            becomes foldable, and swaps instead of remounting. Its fold
            button carries the label (e.g. "N steps") and lights up while the
            header is hovered. */}
        <Collapsible.Header
          rightChildren={rightChildren}
          size="md"
          foldButton={onClick && foldLabel !== undefined ? "icon" : "none"}
          foldLabel={foldLabel}
        >
          {children}
        </Collapsible.Header>
        {expandable && (
          <Collapsible.Content>
            <div className="opal-line-body" data-opal-line-body-inset="flush">
              {expandedContent}
            </div>
          </Collapsible.Content>
        )}
      </Collapsible.Root>
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
