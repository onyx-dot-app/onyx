import { usePopup } from "@/components/admin/connectors/Popup";
import { Button } from "@/components/ui/button";
import { useRef, useState } from "react";
import { FaSpinner } from "react-icons/fa";
import { FiDownload } from "react-icons/fi";

const START_QUERY_HISTORY_EXPORT_URL = "/api/admin/query-history/start-export";
const CHECK_QUERY_HISTORY_EXPORT_STATUS_URL =
  "/api/admin/query-history/export-status";
const DOWNLOAD_QUERY_HISTORY_URL = "/api/admin/query-history/download";
const MAX_RETRIES = 10;
const RETRY_COOLDOWN_MILLISECONDS = 1000;

type StartQueryHistoryExportResponse = { request_id: string };
type CheckQueryHistoryExportStatusResponse = {
  status: "PENDING" | "STARTED" | "SUCCESS" | "FAILURE";
};

// The status of the spinner.
// If it's "static", then no spinning animation should be shown.
// Otherwise, the spinning animation should be shown.
type SpinnerStatus = "static" | "spinning";

const withRequestId = (url: string, requestId: string): string =>
  `${url}?request_id=${requestId}`;

export function DownloadAsCSV() {
  const timerIdRef = useRef<null | number>(null);
  const retryCount = useRef<number>(0);
  const [, rerender] = useState<void>();
  const [spinnerStatus, setSpinnerStatus] = useState<SpinnerStatus>("static");

  const { popup, setPopup } = usePopup();

  const reset = (failure: boolean = false) => {
    setSpinnerStatus("static");
    if (timerIdRef.current) {
      clearInterval(timerIdRef.current);
      timerIdRef.current = null;
    }
    retryCount.current = 0;

    if (failure) {
      setPopup({
        message: "Failed to download the query-history.",
        type: "error",
      });
    }

    rerender();
  };

  const startExport = async () => {
    // If the button is pressed again while we're spinning, then we reset and cancel the request.
    if (spinnerStatus === "spinning") {
      reset();
      return;
    }

    setSpinnerStatus("spinning");
    const response = await fetch(START_QUERY_HISTORY_EXPORT_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
    });

    if (!response.ok) {
      reset(true);
      return;
    }

    const { request_id } =
      (await response.json()) as StartQueryHistoryExportResponse;
    const timer = setInterval(
      () => checkStatus(request_id),
      RETRY_COOLDOWN_MILLISECONDS
    ) as unknown as number;
    timerIdRef.current = timer;
    rerender();
  };

  const checkStatus = async (requestId: string) => {
    rerender();
    if (retryCount.current >= MAX_RETRIES) {
      reset(true);
      return;
    }
    retryCount.current += 1;

    const response = await fetch(
      withRequestId(CHECK_QUERY_HISTORY_EXPORT_STATUS_URL, requestId),
      {
        method: "GET",
      }
    );

    if (!response.ok) {
      reset(true);
      return;
    }

    const { status } =
      (await response.json()) as CheckQueryHistoryExportStatusResponse;

    if (status === "SUCCESS") {
      reset();
      window.location.href = withRequestId(
        DOWNLOAD_QUERY_HISTORY_URL,
        requestId
      );
    } else if (status === "FAILURE") {
      reset(true);
    }
  };

  return (
    <>
      {popup}
      <div className="flex flex-1 flex-col w-full justify-center">
        <Button
          className="flex ml-auto py-2 px-4 border border-border h-fit cursor-pointer hover:bg-accent-background text-sm"
          onClick={startExport}
          variant={spinnerStatus === "spinning" ? "destructive" : "default"}
        >
          {spinnerStatus === "spinning" ? (
            <>
              <FaSpinner className="animate-spin text-2xl" />
              Cancel
            </>
          ) : (
            <>
              <FiDownload className="my-auto mr-2" />
              Download as CSV
            </>
          )}
        </Button>
      </div>
    </>
  );
}
