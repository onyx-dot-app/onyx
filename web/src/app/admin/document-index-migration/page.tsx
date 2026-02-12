"use client";

import { useState } from "react";
import useSWR from "swr";
import { SvgArrowExchange } from "@opal/icons";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import Card from "@/refresh-components/cards/Card";
import { Section } from "@/layouts/general-layouts";
import Text from "@/refresh-components/texts/Text";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import Button from "@/refresh-components/buttons/Button";
import { errorHandlingFetcher } from "@/lib/fetcher";

interface MigrationStatus {
  total_chunks_migrated: number;
  created_at: string | null;
  migration_completed_at: string | null;
}

interface RetrievalStatus {
  enable_opensearch_retrieval: boolean;
}

function formatTimestamp(iso: string): string {
  return new Date(iso).toLocaleString();
}

interface StatusRowProps {
  label: string;
  value: string;
}

function StatusRow({ label, value }: StatusRowProps) {
  return (
    <Section
      flexDirection="row"
      justifyContent="between"
      alignItems="center"
      height="fit"
    >
      <Text mainUiBody text03>
        {label}
      </Text>
      <Text mainUiBody>{value}</Text>
    </Section>
  );
}

function MigrationStatusSection() {
  const { data, isLoading } = useSWR<MigrationStatus>(
    "/api/admin/opensearch-migration/status",
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

  const hasStarted = data?.created_at != null;
  const hasCompleted = data?.migration_completed_at != null;

  return (
    <Card>
      <Text headingH3>Migration Status</Text>

      <StatusRow
        label="Started"
        value={hasStarted ? formatTimestamp(data.created_at!) : "Not started"}
      />

      <StatusRow
        label="Chunks Migrated"
        value={String(data?.total_chunks_migrated ?? 0)}
      />

      <StatusRow
        label="Completed"
        value={
          hasCompleted
            ? formatTimestamp(data.migration_completed_at!)
            : "In progress"
        }
      />
    </Card>
  );
}

function RetrievalSourceSection() {
  const { data, isLoading, mutate } = useSWR<RetrievalStatus>(
    "/api/admin/opensearch-migration/retrieval",
    errorHandlingFetcher
  );
  const [selectedSource, setSelectedSource] = useState<string | null>(null);
  const [updating, setUpdating] = useState(false);

  const serverValue = data?.enable_opensearch_retrieval
    ? "opensearch"
    : "vespa";
  const currentValue = selectedSource ?? serverValue;
  const hasChanges = selectedSource !== null && selectedSource !== serverValue;

  async function handleUpdate() {
    setUpdating(true);
    try {
      const response = await fetch(
        "/api/admin/opensearch-migration/retrieval",
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            enable_opensearch_retrieval: currentValue === "opensearch",
          }),
        }
      );
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

  return (
    <Card>
      <Text headingH3>Retrieval Source</Text>

      <Text mainUiBody text03>
        Controls which document index is used for retrieval.
      </Text>

      <InputSelect
        value={currentValue}
        onValueChange={setSelectedSource}
        disabled={updating}
      >
        <InputSelect.Trigger placeholder="Select retrieval source" />
        <InputSelect.Content>
          <InputSelect.Item value="vespa">Vespa</InputSelect.Item>
          <InputSelect.Item value="opensearch">OpenSearch</InputSelect.Item>
        </InputSelect.Content>
      </InputSelect>

      {hasChanges && (
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
        icon={SvgArrowExchange}
        title="Document Index Migration"
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
