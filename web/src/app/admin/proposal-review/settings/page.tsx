"use client";

import { useRouter } from "next/navigation";
import useSWR, { mutate } from "swr";
import { IllustrationContent } from "@opal/layouts";
import SvgNoResult from "@opal/illustrations/no-result";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SvgSettings } from "@opal/icons";
import SettingsForm from "@/app/admin/proposal-review/components/SettingsForm";
import type {
  ConfigResponse,
  ConfigUpdate,
} from "@/app/admin/proposal-review/interfaces";

const API_URL = "/api/proposal-review/config";

function ProposalReviewSettingsPage() {
  const router = useRouter();
  const {
    data: config,
    isLoading,
    error,
  } = useSWR<ConfigResponse>(API_URL, errorHandlingFetcher);

  async function handleSave(update: ConfigUpdate) {
    const res = await fetch(API_URL, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(update),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Failed to save settings");
    }
    await mutate(API_URL);
  }

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={SvgSettings}
        title="Jira Integration"
        description="Configure which Jira connector to use and how fields are mapped."
        separator
        backButton
        onBack={() => router.push("/admin/proposal-review")}
      />
      <SettingsLayouts.Body>
        {isLoading && <SimpleLoader />}
        {error && (
          <IllustrationContent
            illustration={SvgNoResult}
            title="Error loading settings"
            description={
              error?.info?.message || error?.info?.detail || "An error occurred"
            }
          />
        )}
        {config && (
          <SettingsForm
            config={config}
            onSave={handleSave}
            onCancel={() => router.push("/admin/proposal-review")}
          />
        )}
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}

export default function Page() {
  return <ProposalReviewSettingsPage />;
}
