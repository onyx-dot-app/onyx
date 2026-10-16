"use client";

import { useTranslations } from "next-intl";
import { Code, CopyButton, Popover, ShadowDiv, Text } from "@opal/components";
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
      width="2.5xl"
      side="left"
      align="start"
      aria-label={t("tags.stackTrace")}
    >
      <Section
        alignItems="stretch"
        gap={1}
        padding={1}
        height="auto"
        className="min-h-0"
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
            alignItems="center"
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
          <Code tint showCopyButton={false}>
            {trace}
          </Code>
        </ShadowDiv>
      </Section>
    </Popover.Content>
  );
}
