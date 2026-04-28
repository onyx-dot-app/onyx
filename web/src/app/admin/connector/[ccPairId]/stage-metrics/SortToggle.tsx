"use client";

import { Button, Text } from "@opal/components";
import * as GeneralLayouts from "@/layouts/general-layouts";
import { SortMode } from "./interfaces";

interface SortToggleProps {
  sortMode: SortMode;
  onChange: (mode: SortMode) => void;
}

export default function SortToggle({ sortMode, onChange }: SortToggleProps) {
  return (
    <GeneralLayouts.Section
      flexDirection="row"
      justifyContent="start"
      alignItems="center"
      width="fit"
      height="fit"
      gap={0.5}
    >
      <Text font="secondary-body" color="text-03">
        Sort:
      </Text>
      <Button
        prominence={sortMode === "pipeline" ? "secondary" : "tertiary"}
        size="sm"
        onClick={() => onChange("pipeline")}
      >
        Pipeline order
      </Button>
      <Button
        prominence={sortMode === "time-taken" ? "secondary" : "tertiary"}
        size="sm"
        onClick={() => onChange("time-taken")}
      >
        Time taken
      </Button>
    </GeneralLayouts.Section>
  );
}
