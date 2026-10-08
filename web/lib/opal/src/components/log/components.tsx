"use client";

import "@opal/components/log/styles.css";
import { useCallback, useState } from "react";
import { Interactive, type InteractiveStatelessInteraction } from "@opal/core";
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

interface LogProps {
  /** The line's status: it colours the icon and tints the hover. */
  variant?: StatusVariants;
  /** Shown at 1rem, in the variant's colour. */
  icon: IconFunctionComponent;
  /** What the line is about. One line, at most 10rem wide. */
  title: string | RichStr;
  /** What happened. One line, filling the rest of the row. */
  details?: string | RichStr;
  /** Trailing content, such as a tag or an action. Not padded. */
  rightChildren?: React.ReactNode;
  /**
   * Overrides the line's interaction state, for an owner that highlights
   * one line (e.g. the one the keyboard is on). Unset, it follows the
   * pointer.
   */
  interaction?: InteractiveStatelessInteraction;
}

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
 * content, 2.25rem tall. The variant colours the icon and tints the row on
 * hover. A title or details too long for its line shows in full in a
 * tooltip.
 */
function Log({
  variant = "default",
  icon: Icon,
  title,
  details,
  rightChildren,
  interaction,
}: LogProps) {
  const [titleRef, titleClamped] = useClamped();
  const [detailsRef, detailsClamped] = useClamped();

  return (
    <Interactive.Stateless
      variant="default"
      prominence="internal"
      interaction={interaction}
    >
      <Interactive.Container
        size="lg"
        width="full"
        rounding={2}
        data-opal-log-variant={variant}
      >
        <Section
          flexDirection="row"
          justifyContent="start"
          alignItems="center"
          gap={1}
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
                color="text-04"
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
              height="fit"
              className="min-w-0 flex-1"
            >
              {details !== undefined && (
                <Text
                  font="main-ui-body"
                  color="text-03"
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
      </Interactive.Container>
    </Interactive.Stateless>
  );
}

export { Log, type LogProps };
