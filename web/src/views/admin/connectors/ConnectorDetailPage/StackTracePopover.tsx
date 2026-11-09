"use client";

import { useRef } from "react";
import { useTranslations } from "next-intl";
import { Code, CopyButton, Popover, ShadowDiv, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import {
  PLACEMENT_PROPS,
  type PopoverPlacement,
} from "@/views/admin/connectors/ConnectorDetailPage/popoverPlacement";

export interface StackTracePopoverContentProps {
  runId: number;
  trace: string;
  placement: PopoverPlacement;
}

// The header text's distance from the panel's top edge: the border, the content's and the panel's padding, and the 28 px header row's slack over the 16 px line. Beside, the panel rises by it so the header sits on the chip's text line.
const HEADER_TEXT_INSET = 1 + 4 + 8 + 6;

/** A run's stack trace beside the side panel or below its card, with a copy button. The caller provides the Popover and its trigger. */
export default function StackTracePopoverContent({
  runId,
  trace,
  placement,
}: StackTracePopoverContentProps) {
  const t = useTranslations("admin.connector.activity");
  const focusRef = useRef<HTMLDivElement>(null);
  return (
    <Popover.Content
      width={120}
      {...PLACEMENT_PROPS[placement]}
      alignOffset={placement === "beside" ? -HEADER_TEXT_INSET : undefined}
      aria-label={t("tags.stackTrace")}
      // Focus the panel, not its first button, so the copy tooltip opens only on hover.
      onOpenAutoFocus={(event) => {
        event.preventDefault();
        focusRef.current?.focus();
      }}
    >
      {/* Focused only to hold focus inside the panel, so it draws no ring. */}
      <Section
        ref={focusRef}
        tabIndex={-1}
        alignItems="stretch"
        gap={1}
        padding={2}
        height="auto"
        className="min-h-0 outline-hidden"
      >
        <Section
          flexDirection="row"
          justifyContent="between"
          alignItems="center"
          gap={1}
          height="fit"
          className="shrink-0"
        >
          <Section
            flexDirection="row"
            justifyContent="start"
            alignItems="center"
            gap={0.25}
            height="fit"
            className="min-w-0 flex-1"
          >
            <Text font="secondary-action" color="text-03" maxLines={1}>
              {t("trace.header", { id: runId })}
            </Text>
          </Section>
          {/* Outside the scroll area, so the copy button stays in reach on a long trace. */}
          <CopyButton
            prominence="tertiary"
            size="md"
            getCopyText={() => trace}
            aria-label={t("trace.copy")}
          />
        </Section>
        <ShadowDiv className="max-h-120 overflow-x-auto">
          <Code tint showCopyButton={false}>
            {trace}
          </Code>
        </ShadowDiv>
      </Section>
    </Popover.Content>
  );
}
