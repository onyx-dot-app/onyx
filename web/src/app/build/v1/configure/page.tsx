"use client";

import { useState, useEffect, useCallback } from "react";
import useSWR from "swr";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { Section } from "@/layouts/general-layouts";
import * as InputLayouts from "@/layouts/input-layouts";
import { useLlmManager } from "@/lib/hooks";
import { useBuildSessionStore } from "@/app/build/hooks/useBuildSessionStore";
import LLMPopover from "@/refresh-components/popovers/LLMPopover";
import Text from "@/refresh-components/texts/Text";
import Card from "@/refresh-components/cards/Card";
import { SvgPlug, SvgSettings } from "@opal/icons";
import { FiInfo } from "react-icons/fi";
import { ValidSources } from "@/lib/types";
import { errorHandlingFetcher } from "@/lib/fetcher";
import ConnectorCard, {
  BuildConnectorConfig,
} from "@/app/build/v1/configure/components/ConnectorCard";
import ConfigureConnectorModal from "@/app/build/v1/configure/components/ConfigureConnectorModal";
import ComingSoonConnectors from "@/app/build/v1/configure/components/ComingSoonConnectors";
import DemoDataConfirmModal from "@/app/build/v1/configure/components/DemoDataConfirmModal";
import { ConfirmEntityModal } from "@/components/modals/ConfirmEntityModal";
import { getSourceMetadata } from "@/lib/sources";
import { deleteConnector } from "@/app/build/services/apiServices";
import BackButton from "@/refresh-components/buttons/BackButton";
import { useRouter } from "next/navigation";
import { OAUTH_STATE_KEY } from "@/app/build/v1/constants";
import Separator from "@/refresh-components/Separator";
import Switch from "@/refresh-components/inputs/Switch";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";
import BuildOnboardingModal from "@/app/build/onboarding/components/BuildOnboardingModal";
import NotAllowedModal from "@/app/build/onboarding/components/NotAllowedModal";
import { useLLMProviders } from "@/lib/hooks/useLLMProviders";
import { useUser } from "@/components/user/UserProvider";
import { updateUserPersonalization } from "@/lib/userSettings";
import {
  WORK_AREA_OPTIONS,
  LEVEL_OPTIONS,
  getBuildUserPersona,
  setBuildUserPersona,
} from "@/app/build/onboarding/constants";
import { BuildUserInfo } from "@/app/build/onboarding/types";

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
  const { refreshUser, user, isAdmin, isCurator } = useUser();
  const { llmProviders, refetch: refetchLlmProviders } = useLLMProviders();
  const [selectedConnector, setSelectedConnector] =
    useState<SelectedConnectorState | null>(null);
  const [connectorToDelete, setConnectorToDelete] =
    useState<BuildConnectorConfig | null>(null);
  const [showPersonaModal, setShowPersonaModal] = useState(false);
  const [showNotAllowedModal, setShowNotAllowedModal] = useState(false);
  const [showDemoDataConfirmModal, setShowDemoDataConfirmModal] =
    useState(false);
  const [pendingDemoDataEnabled, setPendingDemoDataEnabled] = useState<
    boolean | null
  >(null);

  const isBasicUser = !isAdmin && !isCurator;

  // Get store values - update store directly on switch change
  const demoDataEnabled = useBuildSessionStore(
    (state) => state.demoDataEnabled
  );
  const setDemoDataEnabled = useBuildSessionStore(
    (state) => state.setDemoDataEnabled
  );

  // Read persona from cookies
  const existingPersona = getBuildUserPersona();
  const workAreaValue = existingPersona?.workArea || "";
  const levelValue = existingPersona?.level || "";

  // Get display labels
  const workAreaLabel =
    WORK_AREA_OPTIONS.find((o) => o.value === workAreaValue)?.label ||
    workAreaValue;
  const levelLabel =
    LEVEL_OPTIONS.find((o) => o.value === levelValue)?.label || levelValue;

  // Get initial values for the modal
  const existingName = user?.personalization?.name || "";
  const spaceIndex = existingName.indexOf(" ");
  const initialFirstName =
    spaceIndex > 0 ? existingName.slice(0, spaceIndex) : existingName;
  const initialLastName =
    spaceIndex > 0 ? existingName.slice(spaceIndex + 1) : "";

  const hasLlmProvider = (llmProviders?.length ?? 0) > 0;

  // Handle persona update
  const handlePersonaComplete = useCallback(
    async (info: BuildUserInfo) => {
      const fullName = `${info.firstName} ${info.lastName}`.trim();
      await updateUserPersonalization({ name: fullName });

      setBuildUserPersona({
        workArea: info.workArea,
        level: info.level,
      });

      await refreshUser();
      setShowPersonaModal(false);
    },
    [refreshUser]
  );

  const handleNavigateBack = () => {
    router.push("/build/v1");
  };

  const { data, mutate, isLoading } = useSWR<BuildConnectorListResponse>(
    "/api/build/connectors",
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
                  title="Your Demo Persona"
                  description={
                    workAreaLabel && levelLabel
                      ? `${workAreaLabel} ${levelLabel}`
                      : workAreaLabel || "Not set"
                  }
                  center
                >
                  <SimpleTooltip
                    tooltip={
                      !hasLlmProvider
                        ? "Configure an LLM provider first"
                        : undefined
                    }
                    disabled={hasLlmProvider}
                  >
                    <button
                      type="button"
                      onClick={() => setShowPersonaModal(true)}
                      disabled={!hasLlmProvider}
                      className="p-2 rounded-08 text-text-03 hover:bg-background-tint-02 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      <SvgSettings className="w-5 h-5" />
                    </button>
                  </SimpleTooltip>
                </InputLayouts.Horizontal>
              </Card>
              <Card>
                <InputLayouts.Horizontal
                  title="Default LLM"
                  description="Select the language model for your build sessions"
                  center
                >
                  <LLMPopover llmManager={llmManager} />
                </InputLayouts.Horizontal>
              </Card>
              <Separator />
              <div className="w-full flex items-center justify-between">
                <div className="flex flex-col gap-0.25">
                  <Text mainContentEmphasis text04>
                    Connectors
                  </Text>
                  <Text secondaryBody text03>
                    Connect your data sources to build mode
                  </Text>
                </div>
                <div className="w-fit flex-shrink-0">
                  <SimpleTooltip
                    tooltip={
                      !hasActiveConnector
                        ? "Connect and sync a data source to disable demo data"
                        : undefined
                    }
                    disabled={hasActiveConnector}
                  >
                    <Card
                      padding={0.75}
                      className={!hasActiveConnector ? "opacity-50" : ""}
                    >
                      <div
                        className={`flex items-center gap-3 ${
                          !hasActiveConnector ? "pointer-events-none" : ""
                        }`}
                      >
                        <div className="flex items-center gap-2">
                          <SimpleTooltip tooltip="The demo dataset contains 1000 files across various connectors">
                            <span className="inline-flex items-center cursor-help">
                              <FiInfo size={16} className="text-text-03" />
                            </span>
                          </SimpleTooltip>
                          <Text mainUiAction>Use Demo Dataset</Text>
                        </div>
                        <Switch
                          checked={demoDataEnabled}
                          onCheckedChange={(newValue) => {
                            setPendingDemoDataEnabled(newValue);
                            setShowDemoDataConfirmModal(true);
                          }}
                        />
                      </div>
                    </Card>
                  </SimpleTooltip>
                </div>
              </div>
              <div className="w-full grid grid-cols-1 md:grid-cols-2 gap-2 pt-2">
                {connectorStates.map(({ type, config }) => (
                  <ConnectorCard
                    key={type}
                    connectorType={type}
                    config={config}
                    onConfigure={() => {
                      // Only open modal for unconfigured connectors
                      if (!config) {
                        if (isBasicUser) {
                          setShowNotAllowedModal(true);
                        } else {
                          setSelectedConnector({ type, config });
                        }
                      }
                    }}
                    onDelete={() => config && setConnectorToDelete(config)}
                  />
                ))}
              </div>
              <ComingSoonConnectors />
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

      <BuildOnboardingModal
        open={showPersonaModal}
        showLlmSetup={false}
        skipInfoSlides={true}
        llmProviders={llmProviders}
        onComplete={handlePersonaComplete}
        onLlmComplete={async () => {
          await refetchLlmProviders();
        }}
        initialValues={{
          firstName: initialFirstName,
          lastName: initialLastName,
          workArea: workAreaValue,
          level: levelValue,
        }}
      />

      <NotAllowedModal
        open={showNotAllowedModal}
        onClose={() => setShowNotAllowedModal(false)}
      />

      <DemoDataConfirmModal
        open={showDemoDataConfirmModal}
        onClose={() => {
          setShowDemoDataConfirmModal(false);
          setPendingDemoDataEnabled(null);
        }}
        pendingDemoDataEnabled={pendingDemoDataEnabled}
        onConfirm={() => {
          if (pendingDemoDataEnabled !== null) {
            setDemoDataEnabled(pendingDemoDataEnabled);
          }
          setShowDemoDataConfirmModal(false);
          setPendingDemoDataEnabled(null);
        }}
      />
    </SettingsLayouts.Root>
  );
}
