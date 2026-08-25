"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import useSWR from "swr";
import { ContentAction, SettingsLayouts, toast } from "@opal/layouts";
import { Button, Card, MessageCard, Text } from "@opal/components";
import { SvgDownload } from "@opal/icons";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { downloadFile } from "@/lib/download";
import { errorHandlingFetcher, FetchError } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { Section } from "@/layouts/general-layouts";

const route = ADMIN_ROUTES.EXPORT_LOGS;

const DESCRIPTION =
  "Download a zip of server log files to attach to an Onyx support thread.";
const EXPORT_URL = "/api/admin/log-export";
const EXPORT_ID_QUERY_PARAM = "export";
// Export ids are uuid4().hex values; anything else found in the URL is noise.
const EXPORT_ID_PATTERN = /^[0-9a-f]{32}$/;
const FALLBACK_FILENAME = "onyx_logs.zip";
const POLL_INTERVAL_MS = 2_000;
// Give up on a poll that fails this many times in a row (~30s at the poll
// interval); the export's server-side collection window is only 90s, so polling
// through longer outages has no value.
const MAX_CONSECUTIVE_POLL_FAILURES = 15;

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

// Mirrors the export id into the URL (shallow, no navigation) so a refresh or
// shared tab can re-attach to the export.
function writeExportIdToUrl(exportId: string | null): void {
  const url = new URL(window.location.href);
  if (exportId === null) {
    url.searchParams.delete(EXPORT_ID_QUERY_PARAM);
  } else {
    url.searchParams.set(EXPORT_ID_QUERY_PARAM, exportId);
  }
  window.history.replaceState({}, "", url.toString());
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
  // The export eligible for auto-download: one this tab started or watched
  // collecting. A page that loads onto an already-finished export (restored
  // URL) only offers the manual button, so page loads never trigger downloads.
  const armedExportIdRef = useRef<string | null>(null);
  // Pending deferred revocation: cancelling the timer must also revoke the URL.
  const pendingRevokeRef = useRef<{
    timer: ReturnType<typeof setTimeout>;
    url: string;
  } | null>(null);

  // Re-attach to an in-flight export after a refresh or navigation; the id is
  // mirrored into the URL when an export starts. Malformed ids are scrubbed.
  useEffect(() => {
    const fromUrl = new URL(window.location.href).searchParams.get(
      EXPORT_ID_QUERY_PARAM
    );
    if (fromUrl === null) {
      return;
    }
    if (EXPORT_ID_PATTERN.test(fromUrl)) {
      setExportId(fromUrl);
    } else {
      writeExportIdToUrl(null);
    }
  }, []);

  const { data: status, error: statusError } = useSWR<LogExportStatus>(
    exportId === null ? null : SWR_KEYS.logExportStatus(exportId),
    errorHandlingFetcher,
    {
      refreshInterval: (latest) =>
        latest?.state === "ready" ? 0 : POLL_INTERVAL_MS,
    }
  );

  const isCollecting = exportId !== null && status?.state !== "ready";

  const consecutivePollFailuresRef = useRef(0);

  // A definitive 4xx means the export is gone (already cleaned up) or no longer
  // accessible; drop it immediately. Other errors are transient (interval
  // polling keeps running and self-heals), but only up to a cap: a server that
  // stays down must not leave the page collecting forever.
  useEffect(() => {
    if (statusError === undefined) {
      consecutivePollFailuresRef.current = 0;
      return;
    }
    console.error("Log export status poll failed:", statusError);
    consecutivePollFailuresRef.current += 1;

    const isTerminal4xx =
      statusError instanceof FetchError &&
      statusError.status >= 400 &&
      statusError.status < 500;
    if (isTerminal4xx) {
      // An id restored from the URL can be stale (export already swept, or
      // never real); it has no status yet, so scrub it without a toast.
      if (status !== undefined) {
        toast.error("Lost access to the running export. Start a new one.");
      }
    } else if (
      consecutivePollFailuresRef.current >= MAX_CONSECUTIVE_POLL_FAILURES
    ) {
      toast.error(
        "Cannot reach the server to check export progress. Start a new export once it is back."
      );
    } else {
      return;
    }
    consecutivePollFailuresRef.current = 0;
    writeExportIdToUrl(null);
    setExportId(null);
  }, [status, statusError]);

  useEffect(() => {
    return () => {
      if (pendingRevokeRef.current !== null) {
        clearTimeout(pendingRevokeRef.current.timer);
        URL.revokeObjectURL(pendingRevokeRef.current.url);
        pendingRevokeRef.current = null;
      }
    };
  }, []);

  const downloadBundle = useCallback(async (id: string): Promise<void> => {
    // Mark before any await: an attempt is in flight or succeeded, and only
    // failure re-arms the auto-download below. Owning this here keeps every
    // call site (auto-fire, manual retry) consistent.
    downloadedExportIdRef.current = id;
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
      if (pendingRevokeRef.current !== null) {
        clearTimeout(pendingRevokeRef.current.timer);
        URL.revokeObjectURL(pendingRevokeRef.current.url);
      }
      // Released on unmount and on replacement. The rule cannot trace the
      // handle through the pendingRevokeRef object.
      // oxlint-disable-next-line react-doctor/effect-needs-cleanup
      const timer = setTimeout(() => {
        URL.revokeObjectURL(url);
        pendingRevokeRef.current = null;
      }, 0);
      pendingRevokeRef.current = { url, timer };
    } catch (error) {
      console.error("Error downloading log export:", error);
      toast.error("Failed to download the log export.");
      // Un-mark the export so the download can be retried; the bundle stays
      // available in the file store until retention sweeps it.
      downloadedExportIdRef.current = null;
    } finally {
      setIsDownloading(false);
    }
  }, []);

  // Download exactly once per export, as soon as it is ready. Arming happens
  // while the export is still collecting (or at start, in handleExport), so
  // attaching to an already-finished export never auto-fires.
  useEffect(() => {
    if (exportId === null || status === undefined) {
      return;
    }
    if (status.state === "collecting") {
      armedExportIdRef.current = exportId;
      return;
    }
    if (
      armedExportIdRef.current !== exportId ||
      downloadedExportIdRef.current === exportId
    ) {
      return;
    }
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
      armedExportIdRef.current = body.export_id;
      setExportId(body.export_id);
      writeExportIdToUrl(body.export_id);
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
            // Once the export is ready, a missing receipt is final: that
            // worker's logs are not in the bundle.
            label:
              status.state === "ready"
                ? "did not report before the deadline"
                : "collecting...",
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
        <Card border="solid" rounding={4}>
          <Section alignItems="start" height="fit">
            <ContentAction
              sizePreset="main-ui"
              variant="section"
              icon={SvgDownload}
              title="Export logs"
              description="Collects log files from the API server and background workers into a single zip. The download starts automatically once collection finishes."
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
          </Section>
        </Card>
        {exportId !== null && (
          <Card border="solid" rounding={4}>
            <Section alignItems="start" height="fit">
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
              {status?.state === "ready" && (
                <Section flexDirection="row" justifyContent="end" height="fit">
                  <Button
                    prominence="secondary"
                    icon={SvgDownload}
                    onClick={() => void downloadBundle(status.export_id)}
                    disabled={isDownloading}
                  >
                    Download
                  </Button>
                </Section>
              )}
            </Section>
          </Card>
        )}
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
