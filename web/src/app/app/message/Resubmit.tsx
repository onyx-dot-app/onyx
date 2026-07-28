import { useEffect, useMemo, useState } from "react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { SvgChevronDown, SvgChevronRight } from "@opal/icons";
import { Button } from "@opal/components";
import { CopyButton } from "@opal/components";
import { getErrorIcon, getErrorTitle } from "./errorHelpers";
import {
  RateLimitDetails,
  RATE_LIMITED_ERROR_CODE,
} from "@/app/app/interfaces";

const COUNTDOWN_TICK_MS = 1_000;

function formatRateLimitReset(resetMs: number, nowMs: number): string {
  const remainingMs = resetMs - nowMs;
  if (remainingMs <= 0) return "You can try again now.";

  const plural = (n: number, unit: string) =>
    `${n} ${unit}${n === 1 ? "" : "s"}`;
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
      ? resetDate.toLocaleDateString(undefined, {
          month: "short",
          day: "numeric",
        })
      : resetDate.toLocaleTimeString(undefined, {
          hour: "numeric",
          minute: "2-digit",
        });
  return `Resets in ${relative} (${at}).`;
}

function resolveResetMs(
  resetAt?: string,
  retryAfterSeconds?: number
): number | null {
  if (resetAt) {
    const parsed = Date.parse(resetAt);
    if (!Number.isNaN(parsed)) return parsed;
  }
  if (typeof retryAfterSeconds === "number") {
    return Date.now() + retryAfterSeconds * 1_000;
  }
  return null;
}

interface RateLimitBannerProps {
  error: string;
  errorCode: string;
  details: RateLimitDetails;
}

function RateLimitBanner({ error, errorCode, details }: RateLimitBannerProps) {
  const [nowMs, setNowMs] = useState(Date.now());
  const resetMs = useMemo(
    () => resolveResetMs(details.reset_at, details.retry_after_seconds),
    [details.reset_at, details.retry_after_seconds]
  );

  useEffect(() => {
    if (resetMs === null) return;

    setNowMs(Date.now());
    const interval = window.setInterval(
      () => setNowMs(Date.now()),
      COUNTDOWN_TICK_MS
    );
    return () => window.clearInterval(interval);
  }, [resetMs]);

  const resetLine =
    resetMs === null ? null : formatRateLimitReset(resetMs, nowMs);
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

  if (errorCode === RATE_LIMITED_ERROR_CODE) {
    return (
      <RateLimitBanner
        error={error}
        errorCode={errorCode}
        details={(details as RateLimitDetails) ?? {}}
      />
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
