"use client";

import { useTranslations } from "next-intl";
import { CopyButton, Popover, ShadowDiv, Text } from "@opal/components";
import { Section } from "@opal/layouts";

export interface StackTracePopoverContentProps {
  runId: number;
  trace: string;
}

/** A run's stack trace beside its card, with a copy button. The caller provides the Popover and its trigger. */
export default function StackTracePopoverContent({
  runId,
  trace,
}: StackTracePopoverContentProps) {
  const t = useTranslations("admin.connector.activity");
  return (
    <Popover.Content
      side="left"
      align="start"
      aria-label={t("tags.stackTrace")}
      // Focus the panel, not its first button, so the copy tooltip opens only on hover.
      onOpenAutoFocus={(event) => {
        event.preventDefault();
        if (event.currentTarget instanceof HTMLElement) {
          event.currentTarget.focus();
        }
      }}
    >
      <Section
        alignItems="stretch"
        gap={1}
        padding={1}
        height="auto"
        className="min-h-0 w-120 max-w-full"
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
            padding={1}
            height="fit"
            className="min-w-0 flex-1"
          >
            <Text font="secondary-body" color="text-03" maxLines={1}>
              {t("trace.header", { id: runId })}
            </Text>
          </Section>
          <CopyButton
            prominence="tertiary"
            size="xs"
            getCopyText={() => trace}
            aria-label={t("trace.copy")}
          />
        </Section>
        <ShadowDiv className="max-h-120 overflow-x-auto">
          <pre
            dir="ltr"
            className="m-0 p-2 rounded-08 bg-background-neutral-01 whitespace-pre-wrap break-all font-secondary-mono text-text-03"
          >
            {trace}
          </pre>
        </ShadowDiv>
      </Section>
    </Popover.Content>
  );
}
