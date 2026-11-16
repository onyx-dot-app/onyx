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

type LogProps = LineBaseProps &
  LineExpandableProps & {
    /** What the line is about. One line, in a 10rem column. */
    title: string | RichStr;
    /**
     * What happened, filling the rest of the row from its start. Any content:
     * the caller sets its colour and how it fits on one line.
     */
    centerChildren?: React.ReactNode;
    /**
     * Makes the whole log interactive: the line and its body hover and press
     * as one, and a click anywhere on them, except on a link, calls this. A
     * button inside (e.g. a chevron) is its keyboard target; that button's
     * click reaches this too.
     */
    onClick?: () => void;
  };

/**
 * One line of a log or report: a 10rem title column, then centre content,
 * 1rem apart, so the columns of a list of logs read apart. Trailing content
 * goes in `rightChildren`. With `onClick`, the line and its body are one
 * interactive surface.
 */
function Log({
  variant = "default",
  padding = 1,
  icon,
  title,
  centerChildren,
  rightChildren,
  onClick,
  expandable,
  expanded,
  expandedContent,
}: LogProps) {
  const content = (
    <>
      <LineRow padding={padding} icon={icon} rightChildren={rightChildren}>
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
            <Text
              maxLines={1}
              overflowTooltip
              font="secondary-action"
              color="text-03"
            >
              {title}
            </Text>
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
      </LineRow>
      {expandable && <LineBody expanded={expanded}>{expandedContent}</LineBody>}
    </>
  );

  return (
    <LineRoot variant={variant} padding={padding}>
      {onClick ? (
        <LineSurface onClick={onClick}>{content}</LineSurface>
      ) : (
        content
      )}
    </LineRoot>
  );
}

export { Log, type LogProps };
