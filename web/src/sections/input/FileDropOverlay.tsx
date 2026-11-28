"use client";

import { useTranslations } from "next-intl";
import { Text } from "@opal/components";
import { SvgPaperclip } from "@opal/icons";
import { Section } from "@opal/layouts";

export function FileDropOverlay() {
  const t = useTranslations("chat.input.fileDropOverlay");
  return (
    <Section
      width="auto"
      height="auto"
      className="pointer-events-none absolute inset-2 z-40 rounded-16 border-2 border-dashed border-action-selection-05 bg-action-selection-01/40"
    >
      <div role="status">
        <Section
          flexDirection="row"
          width="fit"
          height="fit"
          gap={2}
          padding={2.5}
          className="rounded-full border border-border-01 bg-background-neutral-00 shadow-02"
        >
          <SvgPaperclip className="h-4 w-4 stroke-action-selection-05" />
          <Text font="main-ui-action" color="text-05">
            {t("label")}
          </Text>
        </Section>
      </div>
    </Section>
  );
}
