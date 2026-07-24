"use client";

import { useState } from "react";
import { ContentAction, SettingsLayouts, toast } from "@opal/layouts";
import { Button, MessageCard } from "@opal/components";
import { SvgDownload } from "@opal/icons";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { downloadFile } from "@/lib/download";
import Card from "@/refresh-components/cards/Card";

const route = ADMIN_ROUTES.EXPORT_LOGS;

const DESCRIPTION =
  "Download a zip of server log files to attach to an Onyx support thread.";
const DOWNLOAD_URL = "/api/admin/log-export/download";
const FALLBACK_FILENAME = "onyx_logs.zip";

function extractFilename(response: Response): string {
  const disposition = response.headers.get("Content-Disposition");
  const match = disposition?.match(/filename=([^;]+)/);
  return match?.[1]?.trim() ?? FALLBACK_FILENAME;
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
      const url = URL.createObjectURL(blob);
      downloadFile(extractFilename(response), { url });
      URL.revokeObjectURL(url);
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
