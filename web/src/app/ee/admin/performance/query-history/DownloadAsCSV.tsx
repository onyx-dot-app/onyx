import { Button } from "@/components/ui/button";
import { useRef, useState } from "react";
import { FiDownload } from "react-icons/fi";

const START_QUERY_HISTORY_EXPORT_URL = "/api/admin/query-history/start-export";
const CHECK_QUERY_HISTORY_EXPORT_STATUS_URL =
  "/api/admin/query-history/export-status";
const DOWNLOAD_QUERY_HISTORY_URL = "/api/admin/query-history/download";

type StartQueryHistoryExportResponse = { request_id: string };
type CheckQueryHistoryExportStatusResponse = {
  status: "PENDING" | "STARTED" | "SUCCESS" | "FAILURE";
};

type Status = "NULL" | "PENDING" | "SUCCESS" | "FAILURE";

const withRequestId = (url: string, requestId: string): string =>
  `${url}?request_id=${requestId}`;

export function DownloadAsCSV() {
  const timerIdRef = useRef<null | number>(null);
  const [, rerender] = useState(null);
  const [completionStatus, setCompletionStatus] = useState<Status>("NULL");

  const startExport = async () => {
    setCompletionStatus("PENDING");
    const response = await fetch(START_QUERY_HISTORY_EXPORT_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
    });

    if (!response.ok) {
      setCompletionStatus("FAILURE");
    }

    const { request_id } =
      (await response.json()) as StartQueryHistoryExportResponse;
    const timer = setInterval(
      () => checkStatus(request_id),
      1000
    ) as unknown as number;
    timerIdRef.current = timer;
    rerender(null);
  };

  const checkStatus = async (requestId: string) => {
    if (completionStatus === "SUCCESS" || completionStatus === "FAILURE") {
      return;
    }

    const response = await fetch(
      withRequestId(CHECK_QUERY_HISTORY_EXPORT_STATUS_URL, requestId),
      {
        method: "GET",
      }
    );

    if (!response.ok) {
      setCompletionStatus("FAILURE");
    }

    const { status } =
      (await response.json()) as CheckQueryHistoryExportStatusResponse;

    if (status === "SUCCESS") {
      if (timerIdRef.current) {
        clearInterval(timerIdRef.current);
      }
      window.location.href = withRequestId(
        DOWNLOAD_QUERY_HISTORY_URL,
        requestId
      );
    } else if (status === "FAILURE") {
      if (timerIdRef.current) {
        clearInterval(timerIdRef.current);
      }
      setCompletionStatus(status);
    }
  };

  return (
    <Button
      className="flex ml-auto py-2 px-4 border border-border h-fit cursor-pointer hover:bg-accent-background text-sm"
      onClick={startExport}
    >
      <FiDownload className="my-auto mr-2" />
      Download as CSV
    </Button>
  );
}
