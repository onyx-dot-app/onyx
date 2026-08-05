"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import useSWR from "swr";
import { ContentAction, SettingsLayouts, toast } from "@opal/layouts";
import { Button, MessageCard, Text } from "@opal/components";
import { SvgDownload } from "@opal/icons";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { downloadFile } from "@/lib/download";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { Section } from "@/layouts/general-layouts";
import Card from "@/refresh-components/cards/Card";

const route = ADMIN_ROUTES.EXPORT_LOGS;

const DESCRIPTION =
  "Download a zip of server log files to attach to an Onyx support thread.";
const EXPORT_URL = "/api/admin/log-export";
const FALLBACK_FILENAME = "onyx_logs.zip";
const POLL_INTERVAL_MS = 2_000;

type LogExportReceiptStatus =
  | "uploaded"
  | "duplicate_host"
  | "no_logs_found"
  | "failed";

interface LogExportReceipt {
  worker_name: string;
  hostname: string;
  status: LogExportReceiptStatus;
  file_count: number;
  size_bytes: number;
  error: string | null;
}

interface LogExportStatus {
  export_id: string;
  state: "collecting" | "ready";
  receipts: LogExportReceipt[];
  pending_worker_names: string[];
}

function extractFilename(response: Response): string {
  const disposition = response.headers.get("Content-Disposition");
  const match = disposition?.match(/filename=([^;]+)/);
  return match?.[1]?.trim() ?? FALLBACK_FILENAME;
}

function receiptLabel(receipt: LogExportReceipt): string {
  switch (receipt.status) {
    case "uploaded":
      return `uploaded ${receipt.file_count} file${
        receipt.file_count === 1 ? "" : "s"
      }`;
    case "duplicate_host":
      return "covered by another worker on the same host";
    case "no_logs_found":
      return "no log files found";
    case "failed":
      return receipt.error ? `failed: ${receipt.error}` : "failed";
    default: {
      const exhaustive: never = receipt.status;
      return exhaustive;
    }
  }
}

interface WorkerStatusRowProps {
  workerName: string;
  label: string;
  pending?: boolean;
}

function WorkerStatusRow({
  workerName,
  label,
  pending = false,
}: WorkerStatusRowProps) {
  return (
    <Section flexDirection="row" justifyContent="between" height="fit">
      <Text font="main-ui-body">{workerName}</Text>
      <Text font="main-ui-body" color={pending ? "text-02" : "text-03"}>
        {label}
      </Text>
    </Section>
  );
}

export default function ExportLogsPage() {
  const [exportId, setExportId] = useState<string | null>(null);
  const [isStarting, setIsStarting] = useState(false);
  const [isDownloading, setIsDownloading] = useState(false);
  const downloadedExportIdRef = useRef<string | null>(null);

  const { data: status } = useSWR<LogExportStatus>(
    exportId === null ? null : `${EXPORT_URL}/${exportId}`,
    errorHandlingFetcher,
    {
      refreshInterval: (latest) =>
        latest?.state === "ready" ? 0 : POLL_INTERVAL_MS,
    }
  );

  const isCollecting = exportId !== null && status?.state !== "ready";

  const downloadBundle = useCallback(async (id: string): Promise<void> => {
    setIsDownloading(true);
    try {
      const response = await fetch(`${EXPORT_URL}/${id}/download`);
      if (!response.ok) {
        throw new Error(
          `Log export download failed with status ${response.status}`
        );
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      downloadFile(extractFilename(response), { url });
      // Deferred like downloadFile's content mode: the click's download
      // dereferences the blob URL asynchronously.
      setTimeout(() => URL.revokeObjectURL(url), 0);
    } catch (error) {
      console.error("Error downloading log export:", error);
      toast.error("Failed to download the log export.");
    } finally {
      setIsDownloading(false);
    }
  }, []);

  // Download exactly once per export, as soon as it is ready.
  useEffect(() => {
    if (
      exportId === null ||
      status?.state !== "ready" ||
      downloadedExportIdRef.current === exportId
    ) {
      return;
    }
    downloadedExportIdRef.current = exportId;
    void downloadBundle(exportId);
  }, [exportId, status, downloadBundle]);

  async function handleExport(): Promise<void> {
    setIsStarting(true);
    try {
      const response = await fetch(EXPORT_URL, { method: "POST" });
      if (response.status === 429) {
        toast.error("A log export is already in progress. Try again shortly.");
        return;
      }
      if (!response.ok) {
        throw new Error(
          `Starting the log export failed with status ${response.status}`
        );
      }
      const body: { export_id: string } = await response.json();
      setExportId(body.export_id);
    } catch (error) {
      console.error("Error starting log export:", error);
      toast.error("Failed to start the log export.");
    } finally {
      setIsStarting(false);
    }
  }

  // One row per worker, alphabetical so rows do not jump around as receipts
  // replace pending entries between polls.
  const workerRows =
    status === undefined
      ? []
      : [
          ...status.receipts.map((receipt) => ({
            workerName: receipt.worker_name,
            label: receiptLabel(receipt),
            pending: false,
          })),
          ...status.pending_worker_names.map((workerName) => ({
            workerName,
            label: "collecting...",
            pending: true,
          })),
        ].sort((a, b) => a.workerName.localeCompare(b.workerName));

  const buttonLabel = isStarting
    ? "Starting..."
    : isCollecting
      ? "Collecting..."
      : isDownloading
        ? "Downloading..."
        : "Export Logs";

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={route.icon}
        title={route.title}
        description={DESCRIPTION}
        divider
      />
      <SettingsLayouts.Body>
        <MessageCard
          variant="warning"
          title="Logs may contain sensitive data"
          description="Log files can include user emails, document titles, search queries, and error payloads. Review the contents before sharing them outside your organization."
        />
        <Card>
          <ContentAction
            sizePreset="main-ui"
            variant="section"
            icon={SvgDownload}
            title="Export logs"
            description="Collects log files from the API server and every background worker into a single zip. The download starts automatically once collection finishes."
            rightChildren={
              <Button
                icon={SvgDownload}
                onClick={handleExport}
                disabled={isStarting || isCollecting || isDownloading}
              >
                {buttonLabel}
              </Button>
            }
          />
        </Card>
        {exportId !== null && (
          <Card>
            {workerRows.length === 0 ? (
              <Text font="main-ui-body" color="text-02">
                Starting collection...
              </Text>
            ) : (
              workerRows.map((row) => (
                <WorkerStatusRow
                  key={row.workerName}
                  workerName={row.workerName}
                  label={row.label}
                  pending={row.pending}
                />
              ))
            )}
          </Card>
        )}
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
