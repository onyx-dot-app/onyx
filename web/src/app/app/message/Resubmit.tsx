import { useState } from "react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { SvgChevronDown, SvgChevronRight } from "@opal/icons";
import { Button } from "@opal/components";
import { CopyButton } from "@opal/components";
import { getErrorIcon, getErrorTitle } from "./errorHelpers";
import {
  RateLimitDetails,
  RATE_LIMITED_ERROR_CODE,
} from "@/app/app/interfaces";

// Turn a 429's reset_at / retry_after_seconds into a human-friendly sentence.
// Returns null if neither field is present (banner falls back to the detail).
function formatRateLimitReset(details: RateLimitDetails): string | null {
  const resetMs = resolveResetMs(details);
  if (resetMs === null) return null;

  const remainingMs = resetMs - Date.now();
  if (remainingMs <= 0) return "You can try again now.";

  const plural = (n: number, unit: string) => `${n} ${unit}${n === 1 ? "" : "s"}`;
  const minutes = Math.ceil(remainingMs / 60_000);
  const hours = Math.ceil(remainingMs / 3_600_000);
  const days = Math.ceil(remainingMs / 86_400_000);
  const relative =
    minutes < 60
      ? plural(minutes, "minute")
      : hours < 48
        ? plural(hours, "hour")
        : plural(days, "day");
  const resetDate = new Date(resetMs);
  // For multi-day resets a date is clearer than just a clock time.
  const at =
    days >= 2
      ? resetDate.toLocaleDateString(undefined, { month: "short", day: "numeric" })
      : resetDate.toLocaleTimeString(undefined, {
          hour: "numeric",
          minute: "2-digit",
        });
  return `Resets in ${relative} (${at}).`;
}

function resolveResetMs(details: RateLimitDetails): number | null {
  if (details.reset_at) {
    const parsed = Date.parse(details.reset_at);
    if (!Number.isNaN(parsed)) return parsed;
  }
  if (typeof details.retry_after_seconds === "number") {
    return Date.now() + details.retry_after_seconds * 1000;
  }
  return null;
}

interface ResubmitProps {
  resubmit: () => void;
}

export const Resubmit: React.FC<ResubmitProps> = ({ resubmit }) => {
  return (
    <div className="flex flex-col items-center justify-center gap-y-2 mt-4">
      <p className="text-sm text-neutral-700 dark:text-neutral-300">
        There was an error with the response.
      </p>
      <Button onClick={resubmit}>Regenerate</Button>
    </div>
  );
};

export const ErrorBanner = ({
  error,
  errorCode,
  isRetryable = true,
  details,
  stackTrace,
  resubmit,
}: {
  error: string;
  errorCode?: string;
  isRetryable?: boolean;
  details?: Record<string, any>;
  stackTrace?: string | null;
  resubmit?: () => void;
}) => {
  const [isStackTraceExpanded, setIsStackTraceExpanded] = useState(false);

  // Usage rate-limit (429): a focused banner with a reset time and no
  // Regenerate affordance — retrying would just re-trip the same limit.
  if (errorCode === RATE_LIMITED_ERROR_CODE) {
    const resetLine = formatRateLimitReset((details as RateLimitDetails) ?? {});
    return (
      <div className="text-red-700 mt-4 text-sm my-auto">
        <Alert variant="broken">
          {getErrorIcon(errorCode)}
          <AlertTitle>{getErrorTitle(errorCode)}</AlertTitle>
          <AlertDescription className="flex flex-col gap-y-1">
            <span>{error || "You've reached your usage limit."}</span>
            {resetLine && (
              <span className="text-xs text-muted-foreground">{resetLine}</span>
            )}
          </AlertDescription>
        </Alert>
      </div>
    );
  }

  return (
    <div className="text-red-700 mt-4 text-sm my-auto">
      <Alert variant="broken">
        {getErrorIcon(errorCode)}
        <AlertTitle>{getErrorTitle(errorCode)}</AlertTitle>
        <AlertDescription className="flex flex-col gap-y-1">
          <span>{error}</span>
          {details?.model && (
            <span className="text-xs text-muted-foreground">
              Model: {details.model}
              {details.provider && ` (${details.provider})`}
            </span>
          )}
          {details?.tool_name && (
            <span className="text-xs text-muted-foreground">
              Tool: {details.tool_name}
            </span>
          )}
          {stackTrace && (
            <div className="mt-2 border-t border-neutral-200 dark:border-neutral-700 pt-2">
              <div className="flex flex-1 items-center justify-between">
                <Button
                  prominence="tertiary"
                  icon={isStackTraceExpanded ? SvgChevronDown : SvgChevronRight}
                  onClick={() => setIsStackTraceExpanded(!isStackTraceExpanded)}
                >
                  Stack trace
                </Button>
                <CopyButton
                  prominence="tertiary"
                  getCopyText={() => stackTrace}
                />
              </div>
              {isStackTraceExpanded && (
                <pre className="mt-2 p-3 bg-neutral-100 dark:bg-neutral-800 border border-neutral-200 dark:border-neutral-700 rounded-sm text-xs text-neutral-700 dark:text-neutral-300 overflow-auto max-h-48 whitespace-pre-wrap font-mono">
                  {stackTrace}
                </pre>
              )}
            </div>
          )}
        </AlertDescription>
      </Alert>
      {isRetryable && resubmit && <Resubmit resubmit={resubmit} />}
    </div>
  );
};
