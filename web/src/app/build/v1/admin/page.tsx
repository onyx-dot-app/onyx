"use client";

import { useState, useEffect } from "react";
import useSWR from "swr";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { Section } from "@/layouts/general-layouts";
import Text from "@/refresh-components/texts/Text";
import Card from "@/refresh-components/cards/Card";
import { SvgPlug } from "@opal/icons";
import { ValidSources } from "@/lib/types";
import { errorHandlingFetcher } from "@/lib/fetcher";
import ConnectorCard, {
  BuildConnectorConfig,
} from "./components/ConnectorCard";
import ConfigureConnectorModal from "./components/ConfigureConnectorModal";

const OAUTH_STATE_KEY = "build_oauth_state";

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
export default function BuildAdminPage() {
  const [selectedConnector, setSelectedConnector] =
    useState<SelectedConnectorState | null>(null);

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

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={SvgPlug}
        title="Build Connectors"
        description="Data sources available to the build agent"
        backButton
      />
      <SettingsLayouts.Body>
        {isLoading ? (
          <Card variant="tertiary">
            <Section alignItems="center" gap={0.5} height="fit">
              <Text mainContentBody>Loading connectors...</Text>
            </Section>
          </Card>
        ) : (
          <Section
            flexDirection="row"
            justifyContent="start"
            alignItems="start"
            gap={1}
            wrap
            height="fit"
          >
            {connectorStates.map(({ type, config }) => (
              <ConnectorCard
                key={type}
                connectorType={type}
                config={config}
                onConfigure={() => setSelectedConnector({ type, config })}
              />
            ))}
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
    </SettingsLayouts.Root>
  );
}
