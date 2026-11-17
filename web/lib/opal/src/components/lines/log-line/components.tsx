"use client";

import { Section } from "@opal/layouts/general/components";
import { Text } from "@opal/components/text/components";
import { Collapsible } from "@opal/components/collapsible/components";
import {
  LineRoot,
  LineRow,
  LineSurface,
  type LineBaseProps,
  type LineExpandableProps,
} from "@opal/components/lines/line-base/components";
import type { RichStr } from "@opal/types";

type LogLineProps = LineBaseProps &
  LineExpandableProps & {
    /** What the line is about. One line, in a 10rem column. */
    title: string | RichStr;
    /**
     * What happened, filling the rest of the row from its start. Any content:
     * the caller sets its colour and how it fits on one line.
     */
    centerChildren?: React.ReactNode;
    /**
     * Makes the line interactive: the row and the body hover and press as
     * one, and a click on the row, except on a link, calls this. Clicks and
     * text selection in the body never do. A button inside (e.g. a chevron)
     * is its keyboard target; that button's click reaches this too.
     */
    onClick?: () => void;
  };

/**
 * One line of a log or report: a 10rem title column, then centre content,
 * 1rem apart, so the columns of a list of logs read apart. Trailing content
 * goes in `rightChildren`. With `onClick`, the line and its body are one
 * surface, and only the row toggles it.
 */
function LogLine({
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
}: LogLineProps) {
  // The open state and the fold are Collapsible's; the hover surface and the
  // row-only toggle are the line's own, so it looks and behaves as before.
  const content = (
    <Collapsible.Root open={!!expandable && expanded}>
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
      {expandable && (
        <Collapsible.Content>
          <div className="opal-line-body">{expandedContent}</div>
        </Collapsible.Content>
      )}
    </Collapsible.Root>
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

export { LogLine, type LogLineProps };
