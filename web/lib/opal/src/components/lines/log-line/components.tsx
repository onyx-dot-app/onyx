"use client";

import { Section } from "@opal/layouts/general/components";
import { Text } from "@opal/components/text/components";
import {
  Line,
  type LineCommonProps,
  type LineExpandableProps,
} from "@opal/components/lines/line/components";
import type { RichStr } from "@opal/types";

type LogLineProps = LineCommonProps &
  LineExpandableProps & {
    /** What the line is about. One line, in a 10rem column. */
    title: string | RichStr;
    /**
     * What happened, filling the rest of the row from its start. Any content:
     * the caller sets its colour and how it fits on one line.
     */
    centerChildren?: React.ReactNode;
  };

/**
 * One line of a log or report: a `Line` whose content is a 10rem title
 * column, then centre content. The two sit 1rem apart, so the columns of a
 * list of lines read apart. Trailing content goes in `rightChildren`.
 */
function LogLine({ title, centerChildren, ...lineProps }: LogLineProps) {
  return (
    <Line {...lineProps}>
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
    </Line>
  );
}

export { LogLine, type LogLineProps };
