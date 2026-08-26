"use client";

import { useTranslations } from "next-intl";
import { Button, Text } from "@opal/components";
import { Section } from "@/layouts/general-layouts";
import { SortMode } from "./interfaces";

interface SortToggleProps {
  sortMode: SortMode;
  onChange: (mode: SortMode) => void;
}

export default function SortToggle({ sortMode, onChange }: SortToggleProps) {
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
      <Text font="secondary-body" color="text-03">
        {t("stageMetrics.sort.label")}
      </Text>
      <Button
        prominence={sortMode === "pipeline" ? "secondary" : "tertiary"}
        size="sm"
        onClick={() => onChange("pipeline")}
      >
        {t("stageMetrics.sort.pipelineOrder.label")}
      </Button>
      <Button
        prominence={sortMode === "time-taken" ? "secondary" : "tertiary"}
        size="sm"
        onClick={() => onChange("time-taken")}
      >
        {t("stageMetrics.sort.timeTaken.label")}
      </Button>
    </Section>
  );
}
