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
import { useTranslations } from "next-intl";

const COUNTDOWN_TICK_MS = 1_000;

// The countdown as data, so the component owns the translated sentence.
type RateLimitReset =
  | { unit: "now" }
  | { unit: "minutes" | "hours" | "days"; count: number; at: string };

function describeRateLimitReset(
  resetMs: number,
  nowMs: number
): RateLimitReset {
  const remainingMs = resetMs - nowMs;
  if (remainingMs <= 0) return { unit: "now" };

  const minutes = Math.ceil(remainingMs / 60_000);
  const hours = Math.ceil(remainingMs / 3_600_000);
  const days = Math.ceil(remainingMs / 86_400_000);
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
  if (minutes < 60) return { unit: "minutes", count: minutes, at };
  if (hours < 48) return { unit: "hours", count: hours, at };
  return { unit: "days", count: days, at };
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
  title: string;
  details: RateLimitDetails;
}

function RateLimitBanner({
  error,
  errorCode,
  title,
  details,
}: RateLimitBannerProps) {
  const t = useTranslations("chat.messages");
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

  function resetLineFor(reset: RateLimitReset): string {
    switch (reset.unit) {
      case "now":
        return t("rateLimitBanner.tryAgainNow.text");
      case "minutes":
        return t("rateLimitBanner.resetsInMinutes.text", {
          count: reset.count,
          at: reset.at,
        });
      case "hours":
        return t("rateLimitBanner.resetsInHours.text", {
          count: reset.count,
          at: reset.at,
        });
      case "days":
        return t("rateLimitBanner.resetsInDays.text", {
          count: reset.count,
          at: reset.at,
        });
    }
  }

  const resetLine =
    resetMs === null
      ? null
      : resetLineFor(describeRateLimitReset(resetMs, nowMs));
  return (
    <div className="text-red-700 mt-4 text-sm my-auto">
      <Alert variant="broken">
        {getErrorIcon(errorCode)}
        <AlertTitle>{title}</AlertTitle>
        <AlertDescription className="flex flex-col gap-y-1">
          <span>{error || t("rateLimitBanner.defaultError.text")}</span>
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
  const t = useTranslations("chat.messages");
  return (
    <div className="flex flex-col items-center justify-center gap-y-2 mt-4">
      <p className="text-sm text-neutral-700 dark:text-neutral-300">
        {t("resubmit.responseError.text")}
      </p>
      <Button onClick={resubmit}>{t("resubmit.regenerateButton.label")}</Button>
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
  const t = useTranslations("chat.messages");
  const [isStackTraceExpanded, setIsStackTraceExpanded] = useState(false);

  const title = getErrorTitle(errorCode, {
    RATE_LIMIT: t("errorBanner.rateLimitExceeded.title"),
    RATE_LIMITED: t("errorBanner.usageLimitReached.title"),
    AUTH_ERROR: t("errorBanner.authError.title"),
    PERMISSION_DENIED: t("errorBanner.permissionDenied.title"),
    CONTEXT_TOO_LONG: t("errorBanner.messageTooLong.title"),
    TOOL_CALL_FAILED: t("errorBanner.toolError.title"),
    CONNECTION_ERROR: t("errorBanner.connectionError.title"),
    SERVICE_UNAVAILABLE: t("errorBanner.serviceUnavailable.title"),
    INIT_FAILED: t("errorBanner.initializationError.title"),
    VALIDATION_ERROR: t("errorBanner.validationError.title"),
    BUDGET_EXCEEDED: t("errorBanner.budgetExceeded.title"),
    MODEL_REFUSAL: t("errorBanner.modelRefusal.title"),
    CONTENT_POLICY: t("errorBanner.contentPolicy.title"),
    BAD_REQUEST: t("errorBanner.badRequest.title"),
    NOT_FOUND: t("errorBanner.resourceNotFound.title"),
    API_ERROR: t("errorBanner.apiError.title"),
    default: t("errorBanner.genericError.title"),
  });

  if (errorCode === RATE_LIMITED_ERROR_CODE) {
    return (
      <RateLimitBanner
        error={error}
        errorCode={errorCode}
        title={title}
        details={(details as RateLimitDetails) ?? {}}
      />
    );
  }

  return (
    <div className="text-red-700 mt-4 text-sm my-auto">
      <Alert variant="broken">
        {getErrorIcon(errorCode)}
        <AlertTitle>{title}</AlertTitle>
        <AlertDescription className="flex flex-col gap-y-1">
          <span>{error}</span>
          {details?.model && (
            <span className="text-xs text-muted-foreground">
              {details.provider
                ? t("errorBanner.modelWithProvider.label", {
                    model: details.model,
                    provider: details.provider,
                  })
                : t("errorBanner.model.label", { model: details.model })}
            </span>
          )}
          {details?.tool_name && (
            <span className="text-xs text-muted-foreground">
              {t("errorBanner.tool.label", { tool: details.tool_name })}
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
                  {t("errorBanner.stackTraceButton.label")}
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
