"use client";

import { useState } from "react";
import { ContentAction, SettingsLayouts, toast } from "@opal/layouts";
import { Button, MessageCard } from "@opal/components";
import { SvgDownload } from "@opal/icons";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import Card from "@/refresh-components/cards/Card";

const route = ADMIN_ROUTES.EXPORT_LOGS;

const DESCRIPTION =
  "Download a zip of server log files to attach to an Onyx support thread.";
const DOWNLOAD_URL = "/api/admin/log-export/download";
const FALLBACK_FILENAME = "onyx_api_server_logs.zip";

function extractFilename(response: Response): string {
  const disposition = response.headers.get("Content-Disposition");
  const match = disposition?.match(/filename=([^;]+)/);
  return match?.[1]?.trim() ?? FALLBACK_FILENAME;
}

function triggerBlobDownload(blob: Blob, filename: string): void {
  const url = window.URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  window.URL.revokeObjectURL(url);
  document.body.removeChild(anchor);
}

export default function ExportLogsPage() {
  const [isDownloading, setIsDownloading] = useState(false);

  async function handleDownload(): Promise<void> {
    setIsDownloading(true);
    try {
      const response = await fetch(DOWNLOAD_URL);
      if (!response.ok) {
        throw new Error(`Log export failed with status ${response.status}`);
      }
      const blob = await response.blob();
      triggerBlobDownload(blob, extractFilename(response));
    } catch (error) {
      console.error("Error exporting logs:", error);
      toast.error("Failed to export logs.");
    } finally {
      setIsDownloading(false);
    }
  }

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
            title="Export api_server logs"
            description="Collects the API server's log files, including rotations, into a single zip. Logs from background workers are not yet included."
            rightChildren={
              <Button
                icon={SvgDownload}
                onClick={handleDownload}
                disabled={isDownloading}
              >
                {isDownloading ? "Exporting..." : "Export Logs"}
              </Button>
            }
          />
        </Card>
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
