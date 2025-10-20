import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { AlertCircle } from "lucide-react";
import Button from "@/refresh-components/buttons/Button";

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
  showStackTrace,
  resubmit,
}: {
  error: string;
  showStackTrace?: () => void;
  resubmit?: () => void;
}) => {
  return (
    <div className="text-red-700 mt-4 text-sm my-auto">
      <Alert variant="broken">
        <AlertCircle className="h-4 w-4" />
        <AlertTitle>Error</AlertTitle>
        <AlertDescription className="flex  gap-x-2">
          {error}
          {showStackTrace && (
            <span
              className="text-red-600 hover:text-red-800 cursor-pointer underline"
              onClick={showStackTrace}
            >
              Show stack trace
            </span>
          )}
        </AlertDescription>
      </Alert>
      {resubmit && <Resubmit resubmit={resubmit} />}
    </div>
  );
};
