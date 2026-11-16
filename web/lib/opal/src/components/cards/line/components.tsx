"use client";

import { Section } from "@opal/layouts/general/components";
import { Text } from "@opal/components/text/components";
import {
  LineBody,
  LineRoot,
  LineRow,
  LineSurface,
  type LineBaseProps,
  type LineExpandableProps,
} from "@opal/components/cards/line-base/components";
import type { RichStr } from "@opal/types";

type LineProps = LineBaseProps &
  LineExpandableProps & {
    /** What the line is about. Fills the row, on one line. */
    title: string | RichStr;
    /**
     * Makes the row interactive: it hovers and presses, and a click on it,
     * except on a link, calls this. The body never does. A button in
     * `rightChildren` (e.g. a chevron) is its keyboard target; that button's
     * click reaches this too.
     */
    onClick?: () => void;
  };

/**
 * One line of a list or a timeline: an icon, a title and trailing content,
 * 1.75rem tall plus its padding. The variant colours the icon; a heavy
 * variant also tints the line, and its body when expanded. A title too long
 * for the row shows in full in a tooltip.
 *
 * With `onClick`, the row is interactive. With `expandable`, a body opens
 * below it while `expanded`. As in an expandable `SelectCard`, only the row
 * is interactive: the body keeps its own clicks and selection.
 */
function Line({
  variant = "default",
  padding = 1,
  icon,
  title,
  rightChildren,
  onClick,
  expandable,
  expanded,
  expandedContent,
}: LineProps) {
  const row = (
    <LineRow padding={padding} icon={icon} rightChildren={rightChildren}>
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
    </LineRow>
  );

  return (
    <LineRoot variant={variant} padding={padding}>
      {onClick ? <LineSurface onClick={onClick}>{row}</LineSurface> : row}
      {expandable && <LineBody expanded={expanded}>{expandedContent}</LineBody>}
    </LineRoot>
  );
}

export { Line, type LineProps };
