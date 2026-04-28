"use client";

import { Button, Text } from "@opal/components";
import { SvgQuestionMarkSmall } from "@opal/icons";
import * as GeneralLayouts from "@/layouts/general-layouts";
import { IndexAttemptStage } from "@/lib/types";
import { cn } from "@opal/utils";
import { STAGE_DESCRIPTIONS, STAGE_LABELS } from "./constants";
import { colorClassForStage } from "./utils";

interface StageLabelCellProps {
  stage: IndexAttemptStage;
}

export default function StageLabelCell({ stage }: StageLabelCellProps) {
  return (
    <GeneralLayouts.Section
      flexDirection="row"
      justifyContent="start"
      alignItems="center"
      width="fit"
      height="fit"
      gap={0.5}
    >
      {/* Inline color swatch: a color-only marker doesn't fit any
          layout primitive, and Tailwind handles the styling fully. */}
      <span
        aria-hidden="true"
        className={cn(
          "inline-block h-2 w-2 rounded-full shrink-0",
          colorClassForStage(stage)
        )}
      />
      <Text font="secondary-body" color="text-05">
        {STAGE_LABELS[stage]}
      </Text>
      <Button
        icon={SvgQuestionMarkSmall}
        prominence="tertiary"
        size="sm"
        tooltip={STAGE_DESCRIPTIONS[stage]}
      />
    </GeneralLayouts.Section>
  );
}
