"use client";

import "@opal/components/log/styles.css";
import { useCallback, useState } from "react";
import type { TextColor } from "@onyx-ai/shared/contracts";
import { Section } from "@opal/layouts/general/components";
import { Text } from "@opal/components/text/components";
import { Tooltip } from "@opal/components/tooltip/components";
import useOverflow from "@opal/hooks/useOverflow";
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
  "default" | "success" | "warning" | "error"
>;

/** How much a line stands out: `heavy` adds a tinted background. */
type LogWeight = "heavy" | "light";

/**
 * A status and its weight, e.g. `"error-heavy"`. `default` has no weight: it
 * is never tinted.
 */
type LogVariant = "default" | `${Exclude<LogStatus, "default">}-${LogWeight}`;

interface LogProps {
  /** Colours the icon; a heavy variant also colours the details and tints the line. */
  variant?: LogVariant;
  /** Shown at 1rem, in the status colour. */
  icon: IconFunctionComponent;
  /** What the line is about. One line, at most 10rem wide. */
  title: string | RichStr;
  /** What happened. One line, filling the rest of the row. */
  details?: string | RichStr;
  /** Trailing content, such as a tag or an action. Not padded. */
  rightChildren?: React.ReactNode;
}

// A heavy line's details take its status colour; a light line's stay neutral,
// so only the icon carries the status.
const VARIANTS: Record<
  LogVariant,
  { status: LogStatus; weight: LogWeight; details: TextColor }
> = {
  default: { status: "default", weight: "light", details: "text-03" },
  "success-heavy": {
    status: "success",
    weight: "heavy",
    details: "status-success-05",
  },
  "success-light": { status: "success", weight: "light", details: "text-04" },
  "warning-heavy": {
    status: "warning",
    weight: "heavy",
    details: "theme-amber-05",
  },
  "warning-light": { status: "warning", weight: "light", details: "text-04" },
  "error-heavy": {
    status: "error",
    weight: "heavy",
    details: "status-error-05",
  },
  "error-light": { status: "error", weight: "light", details: "text-04" },
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * A ref for a wrapper of one clamped `Text`, and whether that text is
 * clamped. `Text` takes no ref, so the wrapper finds it by its marker.
 */
function useClamped(): [(node: HTMLElement | null) => void, boolean] {
  const [text, setText] = useState<HTMLElement | null>(null);
  const ref = useCallback((node: HTMLElement | null) => {
    setText(node?.querySelector<HTMLElement>("[data-opal-log-text]") ?? null);
  }, []);
  return [ref, useOverflow(text)];
}

// ---------------------------------------------------------------------------
// Log
// ---------------------------------------------------------------------------

/**
 * One line of a log or report: an icon, a title, details, and trailing
 * content, 2.25rem tall. Not interactive. The variant colours the icon; a
 * heavy variant also colours the details and tints the line. A title or details too long for
 * its line shows in full in a tooltip.
 */
function Log({
  variant = "default",
  icon: Icon,
  title,
  details,
  rightChildren,
}: LogProps) {
  const { status, weight, details: detailsColor } = VARIANTS[variant];
  const [titleRef, titleClamped] = useClamped();
  const [detailsRef, detailsClamped] = useClamped();

  return (
    <Section
      flexDirection="row"
      justifyContent="start"
      height={2.25}
      padding={2}
      gap={1}
      className="opal-log"
      data-opal-log-status={status}
      data-opal-log-weight={weight}
    >
      <Section width="fit" height="fit" padding={0.5}>
        <Icon size={16} className="opal-log-icon" />
      </Section>

      <Tooltip tooltip={titleClamped ? title : undefined} side="top">
        <Section
          ref={titleRef}
          width="fit"
          height="fit"
          className="min-w-0 max-w-[10rem]"
        >
          <Text
            font="secondary-action"
            color="text-03"
            maxLines={1}
            data-opal-log-text=""
          >
            {title}
          </Text>
        </Section>
      </Tooltip>

      <Tooltip tooltip={detailsClamped ? details : undefined} side="top">
        <Section
          ref={detailsRef}
          justifyContent="start"
          alignItems="stretch"
          height="fit"
          className="min-w-0 flex-1"
        >
          {details !== undefined && (
            <Text
              as="p"
              font="main-ui-body"
              color={detailsColor}
              textPosition="text-start"
              maxLines={1}
              data-opal-log-text=""
            >
              {details}
            </Text>
          )}
        </Section>
      </Tooltip>

      {rightChildren}
    </Section>
  );
}

export { Log, type LogProps, type LogStatus, type LogVariant, type LogWeight };
