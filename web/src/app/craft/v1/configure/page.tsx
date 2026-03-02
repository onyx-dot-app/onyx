"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { Section } from "@/layouts/general-layouts";
import * as InputLayouts from "@/layouts/input-layouts";
import {
  useBuildSessionStore,
  useIsPreProvisioning,
} from "@/app/craft/hooks/useBuildSessionStore";
import SandboxStatusIndicator from "@/app/craft/components/SandboxStatusIndicator";
import { useBuildLlmSelection } from "@/app/craft/hooks/useBuildLlmSelection";
import { useBuildConnectors } from "@/app/craft/hooks/useBuildConnectors";
import { BuildLLMPopover } from "@/app/craft/components/BuildLLMPopover";
import Text from "@/refresh-components/texts/Text";
import Card from "@/refresh-components/cards/Card";
import {
  SvgPlug,
  SvgSettings,
  SvgChevronDown,
  SvgInfoSmall,
} from "@opal/icons";
import { ValidSources } from "@/lib/types";
import ConnectorCard, {
  BuildConnectorConfig,
} from "@/app/craft/v1/configure/components/ConnectorCard";
import ConfigureConnectorModal from "@/app/craft/v1/configure/components/ConfigureConnectorModal";
import ComingSoonConnectors from "@/app/craft/v1/configure/components/ComingSoonConnectors";
import DemoDataConfirmModal from "@/app/craft/v1/configure/components/DemoDataConfirmModal";
import UserLibraryModal from "@/app/craft/v1/configure/components/UserLibraryModal";
import {
  ConnectorInfoOverlay,
  ReprovisionWarningOverlay,
} from "@/app/craft/v1/configure/components/ConfigureOverlays";
import { ConfirmEntityModal } from "@/components/modals/ConfirmEntityModal";
import { getSourceMetadata } from "@/lib/sources";
import { deleteConnector } from "@/app/craft/services/apiServices";
import Button from "@/refresh-components/buttons/Button";
import {
  OAUTH_STATE_KEY,
  getDemoDataEnabled,
  setDemoDataCookie,
} from "@/app/craft/v1/constants";
import Separator from "@/refresh-components/Separator";
import Switch from "@/refresh-components/inputs/Switch";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";
import NotAllowedModal from "@/app/craft/onboarding/components/NotAllowedModal";
import { useOnboarding } from "@/app/craft/onboarding/BuildOnboardingProvider";
import { useLLMProviders } from "@/hooks/useLLMProviders";
import { useUser } from "@/providers/UserProvider";
import { getProviderIcon } from "@/app/admin/configuration/llm/utils";
import {
  getBuildUserPersona,
  getPersonaInfo,
  getPositionText,
  DEMO_COMPANY_NAME,
  BuildLlmSelection,
  BUILD_MODE_PROVIDERS,
} from "@/app/craft/onboarding/constants";

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
  ValidSources.Airtable,
  ValidSources.CraftFile, // User's uploaded files
];

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
  const { isAdmin, isCurator } = useUser();
  const { llmProviders } = useLLMProviders();
  const { openPersonaEditor, openLlmSetup } = useOnboarding();
  const [selectedConnector, setSelectedConnector] =
    useState<SelectedConnectorState | null>(null);
  const [connectorToDelete, setConnectorToDelete] =
    useState<BuildConnectorConfig | null>(null);
  const [showNotAllowedModal, setShowNotAllowedModal] = useState(false);
  const [showDemoDataConfirmModal, setShowDemoDataConfirmModal] =
    useState(false);
  const [showUserLibraryModal, setShowUserLibraryModal] = useState(false);
  const [pendingDemoDataEnabled, setPendingDemoDataEnabled] = useState<
    boolean | null
  >(null);

  // Pending state for tracking unsaved changes
  const [pendingLlmSelection, setPendingLlmSelection] =
    useState<BuildLlmSelection | null>(null);
  const [pendingDemoData, setPendingDemoData] = useState<boolean | null>(null);
  const [userLibraryChanged, setUserLibraryChanged] = useState(false);
  const [isUpdating, setIsUpdating] = useState(false);

  // Track original values (set on mount and after Update)
  const [originalLlmSelection, setOriginalLlmSelection] =
    useState<BuildLlmSelection | null>(null);
  const [originalDemoData, setOriginalDemoData] = useState<boolean | null>(
    null
  );

  const isBasicUser = !isAdmin && !isCurator;
  const isPreProvisioning = useIsPreProvisioning();

  // Build mode LLM selection (cookie-based)
  const { selection: llmSelection, updateSelection: updateLlmSelection } =
    useBuildLlmSelection(llmProviders);

  // Read demo data from cookie (single source of truth)
  const [demoDataEnabled, setDemoDataEnabledLocal] = useState(() =>
    getDemoDataEnabled()
  );

  // Get store values
  const clearPreProvisionedSession = useBuildSessionStore(
    (state) => state.clearPreProvisionedSession
  );
  const ensurePreProvisionedSession = useBuildSessionStore(
    (state) => state.ensurePreProvisionedSession
  );

  // Initialize pending state from current values on mount
  useEffect(() => {
    if (llmSelection && pendingLlmSelection === null) {
      setPendingLlmSelection(llmSelection);
      setOriginalLlmSelection(llmSelection);
    }
  }, [llmSelection, pendingLlmSelection]);

  useEffect(() => {
    if (pendingDemoData === null) {
      setPendingDemoData(demoDataEnabled);
      setOriginalDemoData(demoDataEnabled);
    }
  }, [demoDataEnabled, pendingDemoData]);

  // Compute whether there are unsaved changes
  const hasChanges = useMemo(() => {
    const llmChanged =
      pendingLlmSelection !== null &&
      originalLlmSelection !== null &&
      (pendingLlmSelection.provider !== originalLlmSelection.provider ||
        pendingLlmSelection.modelName !== originalLlmSelection.modelName);

    const demoDataChanged =
      pendingDemoData !== null &&
      originalDemoData !== null &&
      pendingDemoData !== originalDemoData;

    return llmChanged || demoDataChanged || userLibraryChanged;
  }, [
    pendingLlmSelection,
    pendingDemoData,
    originalLlmSelection,
    originalDemoData,
    userLibraryChanged,
  ]);

  // Compute display name for the pending LLM selection
  const pendingLlmDisplayName = useMemo(() => {
    if (!pendingLlmSelection) return "Select model";

    // 1. Try to get display name from backend llmProviders
    if (llmProviders) {
      for (const provider of llmProviders) {
        const config = provider.model_configurations.find(
          (m) => m.name === pendingLlmSelection.modelName
        );
        if (config) {
          return config.display_name || config.name;
        }
      }
    }

    // 2. Fall back to BUILD_MODE_PROVIDERS labels (for unconfigured providers)
    for (const provider of BUILD_MODE_PROVIDERS) {
      const model = provider.models.find(
        (m) => m.name === pendingLlmSelection.modelName
      );
      if (model) {
        return model.label;
      }
    }

    // 3. Fall back to raw model name
    return pendingLlmSelection.modelName;
  }, [pendingLlmSelection, llmProviders]);

  // Handle LLM selection change - only update pending state
  const handleLlmSelectionChange = useCallback(
    (newSelection: BuildLlmSelection) => {
      setPendingLlmSelection(newSelection);
    },
    []
  );

  // Handle demo data toggle change - only update pending state (after confirmation)
  const handleDemoDataConfirm = useCallback(() => {
    if (pendingDemoDataEnabled !== null) {
      setPendingDemoData(pendingDemoDataEnabled);
    }
    setShowDemoDataConfirmModal(false);
    setPendingDemoDataEnabled(null);
  }, [pendingDemoDataEnabled]);

  // Restore changes - revert pending state to original values
  // Note: User Library changes cannot be reverted (files already uploaded/deleted/toggled)
  // so we just reset the flag - user needs to manually undo file changes if desired
  const handleRestoreChanges = useCallback(() => {
    setPendingLlmSelection(originalLlmSelection);
    setPendingDemoData(originalDemoData);
    setUserLibraryChanged(false);
  }, [originalLlmSelection, originalDemoData]);

  // Update - apply pending changes and re-provision sandbox
  const handleUpdate = useCallback(async () => {
    setIsUpdating(true);
    try {
      // 1. Apply cookies FIRST (synchronous) - these are the user's preferences
      // This ensures settings are persisted even if user navigates away during async operations
      if (pendingLlmSelection) {
        updateLlmSelection(pendingLlmSelection);
        setOriginalLlmSelection(pendingLlmSelection);
      }
      if (pendingDemoData !== null) {
        // Update cookie (single source of truth)
        setDemoDataCookie(pendingDemoData);
        // Update local state for UI reactivity
        setDemoDataEnabledLocal(pendingDemoData);
        setOriginalDemoData(pendingDemoData);
      }

      // 2. Clear pre-provisioned session (may wait if provisioning in progress)
      await clearPreProvisionedSession();

      // 3. Start provisioning a new session with updated settings
      ensurePreProvisionedSession();

      // 4. Reset User Library change flag (sandbox now has the updated files)
      setUserLibraryChanged(false);
    } catch (error) {
      console.error("Failed to update settings:", error);
    } finally {
      setIsUpdating(false);
    }
  }, [
    pendingLlmSelection,
    pendingDemoData,
    updateLlmSelection,
    clearPreProvisionedSession,
    ensurePreProvisionedSession,
  ]);

  // Read persona from cookies
  const existingPersona = getBuildUserPersona();
  const workAreaValue = existingPersona?.workArea;
  const levelValue = existingPersona?.level;

  // Get persona info from mapping
  // If workAreaValue and levelValue exist, personaInfo will always be defined
  // (all combinations are mapped in PERSONA_MAPPING)
  const personaInfo =
    workAreaValue && levelValue
      ? getPersonaInfo(workAreaValue, levelValue)
      : undefined;

  // Get persona name (split into first and last)
  const personaName = personaInfo?.name;
  const [firstName, ...lastNameParts] = personaName?.split(" ") || [];
  const lastName = lastNameParts.join(" ") || "";

  // Get position text using shared helper
  const positionText = workAreaValue
    ? getPositionText(workAreaValue, levelValue)
    : "Not set";

  const hasLlmProvider = (llmProviders?.length ?? 0) > 0;

  const { connectors, hasConnectorEverSucceeded, isLoading, mutate } =
    useBuildConnectors();

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
    config: connectors.find((c) => c.source === type) || null,
  }));

  // Auto-enable demo data when no connectors have ever succeeded.
  // Guard against loading state to avoid a race condition: before the
  // connector fetch completes, hasConnectorEverSucceeded is false (empty
  // array fallback), which would incorrectly re-enable demo data.
  useEffect(() => {
    if (isLoading) return;
    if (!hasConnectorEverSucceeded && !demoDataEnabled) {
      // Update cookie (single source of truth)
      setDemoDataCookie(true);
      // Update local state for UI reactivity
      setDemoDataEnabledLocal(true);
      // Also sync pending state so UI stays consistent
      setPendingDemoData(true);
      setOriginalDemoData(true);
      // Clear and re-provision with new setting
      clearPreProvisionedSession().then(() => {
        ensurePreProvisionedSession();
      });
    }
  }, [
    isLoading,
    hasConnectorEverSucceeded,
    demoDataEnabled,
    clearPreProvisionedSession,
    ensurePreProvisionedSession,
  ]);

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
    <div className="relative w-full h-full">
      {/* Sandbox status indicator - positioned in top-left corner like ChatPanel */}
      <div className="absolute top-3 left-4 z-20">
        <SandboxStatusIndicator />
      </div>

      <SettingsLayouts.Root>
        <SettingsLayouts.Header
          icon={SvgPlug}
          title="Configure Onyx Craft"
          description="Select data sources and your default LLM"
          rightChildren={
            <div className="flex items-center gap-2">
              <Button
                secondary
                onClick={handleRestoreChanges}
                disabled={!hasChanges || isUpdating}
              >
                Restore Changes
              </Button>
              <Button
                onClick={handleUpdate}
                disabled={!hasChanges || isUpdating || isPreProvisioning}
              >
                {isUpdating || isPreProvisioning ? "Updating..." : "Update"}
              </Button>
            </div>
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
                <Card>
                  <InputLayouts.Horizontal
                    title="Your Demo Persona"
                    description={
                      firstName && lastName && positionText
                        ? `${firstName} ${lastName}, ${positionText} at ${DEMO_COMPANY_NAME}`
                        : positionText
                          ? `${positionText} at ${DEMO_COMPANY_NAME}`
                          : "Not set"
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
                        onClick={() => openPersonaEditor()}
                        disabled={!hasLlmProvider}
                        className="p-2 rounded-08 text-text-03 hover:bg-background-tint-02 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        <SvgSettings className="w-5 h-5" />
                      </button>
                    </SimpleTooltip>
                  </InputLayouts.Horizontal>
                </Card>
                <Card
                  className={
                    isUpdating || isPreProvisioning ? "opacity-50" : ""
                  }
                  title={
                    isUpdating || isPreProvisioning
                      ? "Please wait while your session is being provisioned"
                      : undefined
                  }
                >
                  <div
                    className={`w-full ${
                      isUpdating || isPreProvisioning
                        ? "pointer-events-none"
                        : ""
                    }`}
                  >
                    <InputLayouts.Horizontal
                      title="Default LLM"
                      description="Select the language model to craft with"
                      center
                    >
                      <BuildLLMPopover
                        currentSelection={pendingLlmSelection}
                        onSelectionChange={handleLlmSelectionChange}
                        llmProviders={llmProviders}
                        onOpenOnboarding={(providerKey) =>
                          openLlmSetup(providerKey)
                        }
                        disabled={isUpdating || isPreProvisioning}
                      >
                        <button
                          type="button"
                          className="flex items-center gap-2 px-3 py-1.5 rounded-08 border border-border-01 bg-background-tint-00 hover:bg-background-tint-01 transition-colors"
                        >
                          {pendingLlmSelection?.provider &&
                            (() => {
                              const ProviderIcon = getProviderIcon(
                                pendingLlmSelection.provider
                              );
                              return <ProviderIcon className="w-4 h-4" />;
                            })()}
                          <Text mainUiAction>{pendingLlmDisplayName}</Text>
                          <SvgChevronDown className="w-4 h-4 text-text-03" />
                        </button>
                      </BuildLLMPopover>
                    </InputLayouts.Horizontal>
                  </div>
                </Card>
                <Separator />
                <div className="w-full flex items-center justify-between">
                  <div className="flex flex-col gap-0.25">
                    <Text mainContentEmphasis text04>
                      Connectors
                    </Text>
                    <Text secondaryBody text03>
                      Connect your own data sources
                    </Text>
                  </div>
                  <div className="w-fit flex-shrink-0">
                    <SimpleTooltip
                      tooltip={
                        isUpdating || isPreProvisioning
                          ? "Please wait while your session is being provisioned"
                          : !hasConnectorEverSucceeded
                            ? "Connect and sync a data source to disable demo data"
                            : undefined
                      }
                      disabled={
                        hasConnectorEverSucceeded &&
                        !isUpdating &&
                        !isPreProvisioning
                      }
                    >
                      <Card
                        padding={0.75}
                        className={
                          !hasConnectorEverSucceeded ||
                          isUpdating ||
                          isPreProvisioning
                            ? "opacity-50"
                            : ""
                        }
                      >
                        <div
                          className={`flex items-center gap-3 ${
                            !hasConnectorEverSucceeded ||
                            isUpdating ||
                            isPreProvisioning
                              ? "pointer-events-none"
                              : ""
                          }`}
                        >
                          <div className="flex items-center gap-2">
                            <SimpleTooltip tooltip="The demo dataset contains 1000 files across various connectors">
                              <span className="inline-flex items-center cursor-help">
                                <SvgInfoSmall
                                  size={16}
                                  className="text-text-03"
                                />
                              </span>
                            </SimpleTooltip>
                            <Text mainUiAction>Use Demo Dataset</Text>
                          </div>
                          <Switch
                            checked={pendingDemoData ?? demoDataEnabled}
                            disabled={
                              isUpdating ||
                              isPreProvisioning ||
                              !hasConnectorEverSucceeded
                            }
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
                  {connectorStates.map(({ type, config }) => {
                    const metadata = getSourceMetadata(type);
                    return (
                      <ConnectorCard
                        key={type}
                        connectorType={type}
                        config={config}
                        onConfigure={() => {
                          // Connectors marked as alwaysConnected open their custom modal
                          if (metadata.alwaysConnected) {
                            setShowUserLibraryModal(true);
                            return;
                          }
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
                    );
                  })}
                </div>
                <ComingSoonConnectors />
              </Section>
            </Section>
          )}

          {/* Sticky overlay for reprovision warning */}
          <div className="sticky z-toast bottom-10 w-fit mx-auto">
            <ReprovisionWarningOverlay
              visible={hasChanges && !isLoading}
              onUpdate={handleUpdate}
              isUpdating={isUpdating || isPreProvisioning}
            />
          </div>

          {/* Fixed overlay for connector info - centered on screen like the modal */}
          <ConnectorInfoOverlay visible={!!selectedConnector} />
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
          onConfirm={handleDemoDataConfirm}
        />

        <UserLibraryModal
          open={showUserLibraryModal}
          onClose={() => setShowUserLibraryModal(false)}
          onChanges={() => setUserLibraryChanged(true)}
        />
      </SettingsLayouts.Root>
    </div>
  );
}
