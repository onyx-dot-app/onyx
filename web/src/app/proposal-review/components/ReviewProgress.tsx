"use client";

import { Text } from "@opal/components";
import { cn } from "@/lib/utils";
import type { ReviewRun } from "@/app/proposal-review/types";

interface ReviewProgressProps {
  reviewStatus: ReviewRun;
}

export default function ReviewProgress({ reviewStatus }: ReviewProgressProps) {
  const { total_rules, completed_rules, status } = reviewStatus;
  const pct =
    total_rules > 0 ? Math.round((completed_rules / total_rules) * 100) : 0;
  const isFailed = status === "FAILED";

  return (
    <div className="flex flex-col gap-2 p-4">
      <div className="flex items-center justify-between">
        <Text font="main-ui-action" color="text-01">
          {isFailed ? "Review failed" : "Evaluating rules..."}
        </Text>
        <Text font="secondary-body" color="text-03">
          {`${completed_rules} / ${total_rules} rules`}
        </Text>
      </div>

      <div className="h-2 w-full rounded-08 bg-background-neutral-03 overflow-hidden">
        <div
          className={cn(
            "h-full rounded-08 transition-all duration-300",
            isFailed
              ? "bg-status-error-03"
              : pct === 100
                ? "bg-status-success-03"
                : "bg-theme-primary-03"
          )}
          style={{ width: `${pct}%` }}
        />
      </div>

      {isFailed && (
        <Text font="secondary-body" color="text-03">
          The review encountered an error. Please try again.
        </Text>
      )}
    </div>
  );
}
