"use client";

import { useMemo, useState } from "react";
import { Text } from "@opal/components";
import { SvgFold, SvgChevronDown } from "@opal/icons";
import { cn } from "@opal/utils";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/refresh-components/Collapsible";

interface CompactionMarkerProps {
  summary: string | null;
}

export default function CompactionMarker({ summary }: CompactionMarkerProps) {
  const [open, setOpen] = useState(false);
  const summaryLines = useMemo(
    () => (summary?.trim() ? summary.replace(/\s+$/, "").split("\n") : []),
    [summary]
  );
  const hasSummary = summaryLines.length > 0;

  function label(withChevron: boolean) {
    return (
      <span className="flex items-center gap-1.5">
        <SvgFold className="size-3.5 shrink-0 stroke-text-04" />
        <Text font="main-ui-muted" color="text-04" nowrap>
          Context compacted to free up space
        </Text>
        {withChevron && (
          <SvgChevronDown
            className={cn(
              "size-3.5 shrink-0 stroke-text-04 transition-transform duration-200",
              "motion-reduce:transition-none",
              open && "rotate-180"
            )}
          />
        )}
      </span>
    );
  }

  if (!hasSummary) {
    return (
      <div className="flex items-center gap-3 py-3">
        <div className="h-px flex-1 bg-border-02" />
        {label(false)}
        <div className="h-px flex-1 bg-border-02" />
      </div>
    );
  }

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <div className="py-3">
        <div className="flex items-center gap-3">
          <div className="h-px flex-1 bg-border-02" />
          <CollapsibleTrigger asChild>
            <button className="flex items-center rounded-08 px-1 py-0.5 transition-colors hover:bg-background-tint-01 motion-reduce:transition-none">
              {label(true)}
            </button>
          </CollapsibleTrigger>
          <div className="h-px flex-1 bg-border-02" />
        </div>
        <CollapsibleContent>
          <div className="mt-3 flex flex-col gap-1 rounded-12 bg-background-tint-01 px-3 py-2.5">
            {summaryLines.map((line, i) =>
              line.trim() ? (
                <Text key={i} as="p" font="secondary-body" color="text-03">
                  {line}
                </Text>
              ) : (
                <div key={i} className="h-2" aria-hidden />
              )
            )}
          </div>
        </CollapsibleContent>
      </div>
    </Collapsible>
  );
}
