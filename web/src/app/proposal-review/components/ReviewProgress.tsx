"use client";

import { Text } from "@opal/components";
import { SvgCheckCircle, SvgAlertCircle } from "@opal/icons";
import { cn } from "@opal/utils";
import type { ReviewRun } from "@/app/proposal-review/types";

interface ReviewProgressProps {
  reviewStatus: ReviewRun;
}

export default function ReviewProgress({ reviewStatus }: ReviewProgressProps) {
  const { total_rules, completed_rules, failed_rules, status } = reviewStatus;
  const pct =
    total_rules > 0 ? Math.round((completed_rules / total_rules) * 100) : 0;
  const isRunning = status === "RUNNING" || status === "PENDING";
  const isCompleted = status === "COMPLETED";
  const isFailed = status === "FAILED";
  const hasErrors = failed_rules > 0;

  return (
    <div className="flex items-center gap-2 flex-1 min-w-0">
      <div
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`Review progress: ${completed_rules} of ${total_rules} rules`}
        className={cn(
          "h-2 flex-1 min-w-[80px] rounded-08 overflow-hidden",
          isCompleted && !hasErrors
            ? "bg-theme-green-01"
            : "bg-background-neutral-03"
        )}
      >
        <div
          className={cn(
            "h-full rounded-08 transition-all duration-300",
            isFailed
              ? "bg-status-error-03"
              : isCompleted && hasErrors
                ? "bg-status-warning-03"
                : isCompleted
                  ? "bg-theme-green-01"
                  : "bg-theme-primary-03"
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
      {isRunning && (
        <Text font="secondary-body" color="text-03" nowrap>
          {failed_rules > 0
            ? `${completed_rules}/${total_rules} (${failed_rules} failed)`
            : `${completed_rules}/${total_rules}`}
        </Text>
      )}
      {isCompleted && !hasErrors && (
        <div className="flex items-center gap-1">
          <SvgCheckCircle className="h-3.5 w-3.5 text-status-success-03" />
          <Text font="secondary-body" color="text-03" nowrap>
            {`${total_rules}/${total_rules}`}
          </Text>
        </div>
      )}
      {isCompleted && hasErrors && (
        <div className="flex items-center gap-1">
          <SvgAlertCircle className="h-3.5 w-3.5 text-status-warning-03" />
          <Text font="secondary-body" color="text-03" nowrap>
            {`${
              total_rules - failed_rules
            }/${total_rules} (${failed_rules} failed)`}
          </Text>
        </div>
      )}
      {isFailed && (
        <div className="flex items-center gap-1">
          <SvgAlertCircle className="h-3.5 w-3.5 text-status-error-03" />
          <Text font="secondary-body" color="text-03" nowrap>
            Failed
          </Text>
        </div>
      )}
    </div>
  );
}
