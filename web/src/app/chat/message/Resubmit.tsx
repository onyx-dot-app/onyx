import { useState } from "react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { SvgChevronDown, SvgChevronRight } from "@opal/icons";
import Button from "@/refresh-components/buttons/Button";
import CopyIconButton from "@/refresh-components/buttons/CopyIconButton";
import { getErrorIcon, getErrorTitle } from "./errorHelpers";

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
                  tertiary
                  leftIcon={
                    isStackTraceExpanded ? SvgChevronDown : SvgChevronRight
                  }
                  onClick={() => setIsStackTraceExpanded(!isStackTraceExpanded)}
                >
                  Stack trace
                </Button>
                <CopyIconButton tertiary getCopyText={() => stackTrace} />
              </div>
              {isStackTraceExpanded && (
                <pre className="mt-2 p-3 bg-neutral-100 dark:bg-neutral-800 border border-neutral-200 dark:border-neutral-700 rounded text-xs text-neutral-700 dark:text-neutral-300 overflow-auto max-h-48 whitespace-pre-wrap font-mono">
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
