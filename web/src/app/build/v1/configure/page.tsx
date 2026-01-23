"use client";

import { useState, useEffect } from "react";
import useSWR from "swr";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { Section } from "@/layouts/general-layouts";
import * as InputLayouts from "@/layouts/input-layouts";
import { useLlmManager } from "@/lib/hooks";
import { useBuildSessionStore } from "@/app/build/hooks/useBuildSessionStore";
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
import Switch from "@/refresh-components/inputs/Switch";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";

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

  // Get store values - update store directly on switch change
  const demoDataEnabled = useBuildSessionStore(
    (state) => state.demoDataEnabled
  );
  const setDemoDataEnabled = useBuildSessionStore(
    (state) => state.setDemoDataEnabled
  );

  const handleNavigateBack = () => {
    router.push("/build/v1");
  };

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

  // Check if there's at least one connector in "connected" (active) state
  const hasActiveConnector = connectorStates.some(
    ({ config }) => config?.status === "connected"
  );

  // Auto-enable demo data when all connectors are disconnected
  useEffect(() => {
    if (!hasActiveConnector && !demoDataEnabled) {
      setDemoDataEnabled(true);
    }
  }, [hasActiveConnector, demoDataEnabled, setDemoDataEnabled]);

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
        description="Select data sources and your build mode LLM"
        rightChildren={<BackButton behaviorOverride={handleNavigateBack} />}
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
              <Card>
                <InputLayouts.Horizontal
                  title="Use Demo Data"
                  description="Demo data set contains 3000 files across all available connectors"
                  center
                >
                  <SimpleTooltip
                    tooltip={
                      !hasActiveConnector
                        ? "Connect and sync a data source to enable demo data"
                        : undefined
                    }
                    disabled={hasActiveConnector}
                  >
                    <Switch
                      checked={demoDataEnabled}
                      onCheckedChange={setDemoDataEnabled}
                      disabled={!hasActiveConnector}
                    />
                  </SimpleTooltip>
                </InputLayouts.Horizontal>
              </Card>
              <Separator />
              <InputLayouts.Label
                title="Connectors"
                description="Connect your data sources to build mode"
              />
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
              <InputLayouts.Label
                title="Advanced Options"
                description="Configure advanced options for your build mode"
              />
              <Card>
                <InputLayouts.Horizontal
                  title="Default LLM"
                  description="Select the language model for your build sessions"
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
