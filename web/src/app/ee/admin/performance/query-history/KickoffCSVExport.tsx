import { usePopup } from "@/components/admin/connectors/Popup";
import { Button } from "@/components/ui/button";
import { useRef, useState } from "react";
import { DateRange } from "../../../../../components/dateRangeSelectors/AdminDateRangeSelector";
import { FaSpinner, FaRegArrowAltCircleUp } from "react-icons/fa";
import { withRequestId, withDateRange } from "./utils";
import {
  CHECK_QUERY_HISTORY_EXPORT_STATUS_URL,
  DOWNLOAD_QUERY_HISTORY_URL,
  MAX_RETRIES,
  PREVIOUS_CSV_TASK_BUTTON_NAME,
  RETRY_COOLDOWN_MILLISECONDS,
} from "./constants";
import {
  CheckQueryHistoryExportStatusResponse,
  SpinnerStatus,
  StartQueryHistoryExportResponse,
} from "./types";

export function KickoffCSVExport({ dateRange }: { dateRange: DateRange }) {
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
    setPopup({
      message: `Generating CSV report. Click the '${PREVIOUS_CSV_TASK_BUTTON_NAME}' button to see all jobs.`,
    });
    const response = await fetch(withDateRange(dateRange), {
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
    if (retryCount.current >= MAX_RETRIES) {
      reset();
      return;
    }
    retryCount.current += 1;
    rerender();

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
          className="flex ml-auto py-2 px-4 h-fit cursor-pointer text-sm w-[140px]"
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
              <FaRegArrowAltCircleUp />
              Kickoff Export
            </>
          )}
        </Button>
      </div>
    </>
  );
}
