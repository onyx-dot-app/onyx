"use client";

import { useState } from "react";
import useSWR from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { ADMIN_ROUTES } from "@/lib/admin-routes";

const route = ADMIN_ROUTES.INDEX_MIGRATION;

import Card from "@/refresh-components/cards/Card";
import { Content, ContentAction } from "@opal/layouts";
import Text from "@/refresh-components/texts/Text";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import Button from "@/refresh-components/buttons/Button";
import { errorHandlingFetcher } from "@/lib/fetcher";

const TOGGLE_DISABLED_MESSAGE =
  "Changing the retrieval source is not currently possible for this instance of Onyx.";

interface MigrationStatus {
  total_chunks_migrated: number;
  created_at: string | null;
  migration_completed_at: string | null;
  approx_chunk_count_in_vespa: number | null;
}

interface RetrievalStatus {
  enable_opensearch_retrieval: boolean;
  toggling_retrieval_is_disabled?: boolean;
}

function formatTimestamp(iso: string): string {
  return new Date(iso).toLocaleString();
}

function MigrationStatusSection() {
  const { data, isLoading, error } = useSWR<MigrationStatus>(
    SWR_KEYS.opensearchMigrationStatus,
    errorHandlingFetcher
  );

  if (isLoading) {
    return (
      <Card>
        <Text headingH3>Migration Status</Text>
        <Text mainUiBody text03>
          Loading...
        </Text>
      </Card>
    );
  }

  if (error) {
    return (
      <Card>
        <Text headingH3>Migration Status</Text>
        <Text mainUiBody text03>
          Failed to load migration status.
        </Text>
      </Card>
    );
  }

  const hasStarted = data?.created_at != null;
  const hasCompleted = data?.migration_completed_at != null;
  const isOngoing = hasStarted && !hasCompleted;

  const totalChunksMigrated = data?.total_chunks_migrated ?? 0;
  const approxTotalChunks = data?.approx_chunk_count_in_vespa;

  // Calculate percentage progress if migration is ongoing and we have approx
  // total chunks.
  const shouldShowProgress = isOngoing && approxTotalChunks;
  const progressPercentage = shouldShowProgress
    ? Math.min(99, (totalChunksMigrated / approxTotalChunks) * 100)
    : null;

  return (
    <Card>
      <Text headingH3>Migration Status</Text>

      <ContentAction
        title="Started"
        sizePreset="main-ui"
        variant="section"
        rightChildren={
          <Text mainUiBody>
            {hasStarted ? formatTimestamp(data.created_at!) : "Not started"}
          </Text>
        }
      />

      <ContentAction
        title="Chunks Migrated"
        sizePreset="main-ui"
        variant="section"
        rightChildren={
          <Text mainUiBody>
            {progressPercentage !== null
              ? `${totalChunksMigrated} (approx. progress ${Math.round(
                  progressPercentage
                )}%)`
              : String(totalChunksMigrated)}
          </Text>
        }
      />

      <ContentAction
        title="Completed"
        sizePreset="main-ui"
        variant="section"
        rightChildren={
          <Text mainUiBody>
            {hasCompleted
              ? formatTimestamp(data.migration_completed_at!)
              : hasStarted
                ? "In progress"
                : "Not started"}
          </Text>
        }
      />
    </Card>
  );
}

function RetrievalSourceSection() {
  const { data, isLoading, error, mutate } = useSWR<RetrievalStatus>(
    SWR_KEYS.opensearchMigrationRetrieval,
    errorHandlingFetcher
  );
  const [selectedSource, setSelectedSource] = useState<string | null>(null);
  const [updating, setUpdating] = useState(false);

  const serverValue = data?.enable_opensearch_retrieval
    ? "opensearch"
    : "vespa";
  const currentValue = selectedSource ?? serverValue;
  const hasChanges = selectedSource !== null && selectedSource !== serverValue;
  const togglingDisabled = data?.toggling_retrieval_is_disabled ?? false;

  async function handleUpdate() {
    setUpdating(true);
    try {
      const response = await fetch(SWR_KEYS.opensearchMigrationRetrieval, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          enable_opensearch_retrieval: currentValue === "opensearch",
        }),
      });
      if (!response.ok) {
        throw new Error("Failed to update retrieval setting");
      }
      await mutate();
      setSelectedSource(null);
    } finally {
      setUpdating(false);
    }
  }

  if (isLoading) {
    return (
      <Card>
        <Text headingH3>Retrieval Source</Text>
        <Text mainUiBody text03>
          Loading...
        </Text>
      </Card>
    );
  }

  if (error) {
    return (
      <Card>
        <Text headingH3>Retrieval Source</Text>
        <Text mainUiBody text03>
          Failed to load retrieval settings.
        </Text>
      </Card>
    );
  }

  return (
    <Card>
      <Content
        title="Retrieval Source"
        description="Controls which document index is used for retrieval."
        sizePreset="main-ui"
        variant="section"
      />

      <InputSelect
        value={currentValue}
        onValueChange={setSelectedSource}
        disabled={updating || togglingDisabled}
      >
        <InputSelect.Trigger placeholder="Select retrieval source" />
        <InputSelect.Content>
          <InputSelect.Item value="vespa">Vespa</InputSelect.Item>
          <InputSelect.Item value="opensearch">OpenSearch</InputSelect.Item>
        </InputSelect.Content>
      </InputSelect>

      {togglingDisabled && (
        <Text mainUiBody text03>
          {TOGGLE_DISABLED_MESSAGE}
        </Text>
      )}

      {hasChanges && (
        // TODO(@raunakab): migrate to opal Button once className/iconClassName is resolved
        <Button
          className="self-center"
          onClick={handleUpdate}
          disabled={updating}
        >
          {updating ? "Updating..." : "Update Settings"}
        </Button>
      )}
    </Card>
  );
}

export default function Page() {
  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={route.icon}
        title={route.title}
        description="Monitor the migration from Vespa to OpenSearch and control the active retrieval source."
        separator
      />
      <SettingsLayouts.Body>
        <MigrationStatusSection />
        <RetrievalSourceSection />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
