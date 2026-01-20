"use client";

import { useState, useEffect } from "react";
import useSWR from "swr";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { LineItemLayout, Section } from "@/layouts/general-layouts";
import * as InputLayouts from "@/layouts/input-layouts";
import { useLlmManager } from "@/lib/hooks";
import LLMPopover from "@/refresh-components/popovers/LLMPopover";
import Text from "@/refresh-components/texts/Text";
import Card from "@/refresh-components/cards/Card";
import { SvgPlug } from "@opal/icons";
import { ValidSources } from "@/lib/types";
import { errorHandlingFetcher } from "@/lib/fetcher";
import ConnectorCard, {
  BuildConnectorConfig,
} from "@/app/build/v1/configure/components/ConnectorCard";
import ConfigureConnectorModal from "@/app/build/v1/configure/components/ConfigureConnectorModal";
import { ConfirmEntityModal } from "@/components/modals/ConfirmEntityModal";
import { getSourceMetadata } from "@/lib/sources";
import { deleteConnector } from "@/app/build/services/apiServices";
import BackButton from "@/refresh-components/buttons/BackButton";
import { useRouter } from "next/navigation";
import { OAUTH_STATE_KEY } from "@/app/build/v1/constants";
import Separator from "@/refresh-components/Separator";

// Build mode connectors
const BUILD_CONNECTORS: ValidSources[] = [
  ValidSources.GoogleDrive,
  ValidSources.Gmail,
  ValidSources.Notion,
  ValidSources.GitHub,
  ValidSources.Slack,
  ValidSources.Linear,
  ValidSources.Fireflies,
  ValidSources.Hubspot,
];

interface BuildConnectorListResponse {
  connectors: BuildConnectorConfig[];
}

interface SelectedConnectorState {
  type: ValidSources;
  config: BuildConnectorConfig | null;
}

/**
 * Build Admin Panel - Connector configuration page
 *
 * Renders in the center panel area (replacing ChatPanel + OutputPanel).
 * Uses SettingsLayouts like AgentEditorPage does.
 */
export default function BuildConfigPage() {
  const router = useRouter();
  const llmManager = useLlmManager();
  const [selectedConnector, setSelectedConnector] =
    useState<SelectedConnectorState | null>(null);
  const [connectorToDelete, setConnectorToDelete] =
    useState<BuildConnectorConfig | null>(null);

  const { data, mutate, isLoading } = useSWR<BuildConnectorListResponse>(
    "/api/build/v1/connectors",
    errorHandlingFetcher,
    { refreshInterval: 5000 }
  );

  // Check for OAuth return state on mount
  useEffect(() => {
    const savedState = sessionStorage.getItem(OAUTH_STATE_KEY);
    if (savedState) {
      try {
        const { connectorType, timestamp } = JSON.parse(savedState);
        // Only restore if < 10 minutes old
        if (Date.now() - timestamp < 600000) {
          setSelectedConnector({
            type: connectorType as ValidSources,
            config: null,
          });
        }
      } catch (e) {
        console.error("Failed to parse OAuth state:", e);
      }
      sessionStorage.removeItem(OAUTH_STATE_KEY);
    }
  }, []);

  // Merge configured status with all available build connectors
  const connectorStates = BUILD_CONNECTORS.map((type) => ({
    type,
    config: data?.connectors?.find((c) => c.source === type) || null,
  }));

  const handleDeleteConfirm = async () => {
    if (!connectorToDelete) return;

    try {
      await deleteConnector(
        connectorToDelete.connector_id,
        connectorToDelete.credential_id
      );
      mutate();
    } catch (error) {
      console.error("Failed to delete connector:", error);
    } finally {
      setConnectorToDelete(null);
    }
  };

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={SvgPlug}
        title="Configure Build Mode"
        description="Data sources available to the Build Mode agent"
        rightChildren={
          <BackButton behaviorOverride={() => router.push("/build/v1")} />
        }
      />
      <SettingsLayouts.Body>
        {isLoading ? (
          <Card variant="tertiary">
            <Section alignItems="center" gap={0.5} height="fit">
              <Text mainContentBody>Loading...</Text>
            </Section>
          </Card>
        ) : (
          <Section flexDirection="column" gap={2}>
            <Section
              flexDirection="column"
              alignItems="start"
              gap={0.5}
              height="fit"
            >
              <Text headingH3Muted text03>
                Connectors
              </Text>
              <div className="w-full grid grid-cols-1 md:grid-cols-2 gap-2">
                {connectorStates.map(({ type, config }) => (
                  <ConnectorCard
                    key={type}
                    connectorType={type}
                    config={config}
                    onConfigure={() => {
                      // Only open modal for unconfigured connectors
                      if (!config) {
                        setSelectedConnector({ type, config });
                      }
                    }}
                    onDelete={() => config && setConnectorToDelete(config)}
                  />
                ))}
              </div>
            </Section>

            <Separator />

            <Section alignItems="start" gap={0.5} height="fit">
              <Text headingH3Muted text03>
                Default LLM
              </Text>
              <Card>
                <InputLayouts.Horizontal
                  title="Build Mode LLM"
                  description="Select the language model for Build Mode"
                  center
                >
                  <LLMPopover llmManager={llmManager} />
                </InputLayouts.Horizontal>
              </Card>
            </Section>
          </Section>
        )}
      </SettingsLayouts.Body>

      <ConfigureConnectorModal
        connectorType={selectedConnector?.type || null}
        existingConfig={selectedConnector?.config || null}
        open={!!selectedConnector}
        onClose={() => setSelectedConnector(null)}
        onSuccess={() => {
          setSelectedConnector(null);
          mutate();
        }}
      />

      {connectorToDelete && (
        <ConfirmEntityModal
          danger
          entityType="connector"
          entityName={
            getSourceMetadata(connectorToDelete.source as ValidSources)
              .displayName
          }
          action="disconnect"
          actionButtonText="Disconnect"
          additionalDetails="This will remove access to this data source. You can reconnect it later."
          onClose={() => setConnectorToDelete(null)}
          onSubmit={handleDeleteConfirm}
        />
      )}
    </SettingsLayouts.Root>
  );
}
