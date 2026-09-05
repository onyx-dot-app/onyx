"use client";

import { useTranslations } from "next-intl";
import { Button, Text } from "@opal/components";
import { SvgInfoSmall } from "@opal/icons";
import { Section } from "@/layouts/general-layouts";
import { IndexAttemptStage } from "@/lib/types";
import { cn } from "@opal/utils";
import { STAGE_DESCRIPTION_KEYS, STAGE_LABEL_KEYS } from "./constants";
import { colorClassForStage } from "./utils";

interface StageLabelCellProps {
  stage: IndexAttemptStage;
}

export default function StageLabelCell({ stage }: StageLabelCellProps) {
  const t = useTranslations("admin.connector");

  return (
    <Section
      flexDirection="row"
      justifyContent="start"
      alignItems="center"
      width="fit"
      height="fit"
      gap={2}
    >
      {/* Inline color swatch: a color-only marker doesn't fit any
          layout primitive, and Tailwind handles the styling fully. */}
      <span
        aria-hidden="true"
        className={cn(
          "inline-block h-2 w-2 rounded-full",
          colorClassForStage(stage)
        )}
      />
      <Text font="secondary-body" color="text-05" nowrap>
        {t(STAGE_LABEL_KEYS[stage])}
      </Text>
      <Button
        icon={SvgInfoSmall}
        prominence="tertiary"
        size="sm"
        tooltip={t(STAGE_DESCRIPTION_KEYS[stage])}
      />
    </Section>
  );
}
