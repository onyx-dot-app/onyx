"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { Section } from "@/layouts/general-layouts";
import { InputHorizontal } from "@opal/layouts";
import {
  useBuildSessionStore,
  useIsPreProvisioning,
} from "@/app/craft/hooks/useBuildSessionStore";
import SandboxStatusIndicator from "@/app/craft/components/SandboxStatusIndicator";
import { useBuildLlmSelection } from "@/app/craft/hooks/useBuildLlmSelection";
import { BuildLLMPopover } from "@/app/craft/components/BuildLLMPopover";
import Text from "@/refresh-components/texts/Text";
import Card from "@/refresh-components/cards/Card";
import {
  SvgPlug,
  SvgSettings,
  SvgChevronDown,
  SvgChevronRight,
  SvgFolder,
} from "@opal/icons";
import UserLibraryModal from "@/app/craft/v1/configure/components/UserLibraryModal";
import { Button, Divider } from "@opal/components";
import { useOnboarding } from "@/app/craft/onboarding/BuildOnboardingProvider";
import { useUser } from "@/providers/UserProvider";
import { useLLMProviders } from "@/hooks/useLanguageModels";
import { getModelIcon } from "@/lib/languageModels";
import {
  getBuildUserPersona,
  WORK_AREA_OPTIONS,
  LEVEL_OPTIONS,
  BuildLlmSelection,
  BUILD_MODE_PROVIDERS,
} from "@/app/craft/onboarding/constants";

export default function BuildConfigPage() {
  const { llmProviders } = useLLMProviders();
  const { isAdmin, isCurator } = useUser();
  const canManageConnectors = isAdmin || isCurator;
  const { openUserInfoEditor, openLlmSetup } = useOnboarding();
  const [showUserLibraryModal, setShowUserLibraryModal] = useState(false);

  const [pendingLlmSelection, setPendingLlmSelection] =
    useState<BuildLlmSelection | null>(null);
  const [userLibraryChanged, setUserLibraryChanged] = useState(false);
  const [isUpdating, setIsUpdating] = useState(false);

  const [originalLlmSelection, setOriginalLlmSelection] =
    useState<BuildLlmSelection | null>(null);

  const isPreProvisioning = useIsPreProvisioning();

  const { selection: llmSelection, updateSelection: updateLlmSelection } =
    useBuildLlmSelection(llmProviders);

  const clearPreProvisionedSession = useBuildSessionStore(
    (state) => state.clearPreProvisionedSession
  );
  const ensurePreProvisionedSession = useBuildSessionStore(
    (state) => state.ensurePreProvisionedSession
  );

  useEffect(() => {
    if (llmSelection && pendingLlmSelection === null) {
      setPendingLlmSelection(llmSelection);
      setOriginalLlmSelection(llmSelection);
    }
  }, [llmSelection, pendingLlmSelection]);

  const hasChanges = useMemo(() => {
    const llmChanged =
      pendingLlmSelection !== null &&
      originalLlmSelection !== null &&
      (pendingLlmSelection.provider !== originalLlmSelection.provider ||
        pendingLlmSelection.modelName !== originalLlmSelection.modelName);

    return llmChanged || userLibraryChanged;
  }, [pendingLlmSelection, originalLlmSelection, userLibraryChanged]);

  const pendingLlmDisplayName = useMemo(() => {
    if (!pendingLlmSelection) return "Select model";

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

    for (const provider of BUILD_MODE_PROVIDERS) {
      const model = provider.models.find(
        (m) => m.name === pendingLlmSelection.modelName
      );
      if (model) {
        return model.label;
      }
    }

    return pendingLlmSelection.modelName;
  }, [pendingLlmSelection, llmProviders]);

  const handleLlmSelectionChange = useCallback(
    (newSelection: BuildLlmSelection) => {
      setPendingLlmSelection(newSelection);
    },
    []
  );

  const handleRestoreChanges = useCallback(() => {
    setPendingLlmSelection(originalLlmSelection);
    setUserLibraryChanged(false);
  }, [originalLlmSelection]);

  const handleUpdate = useCallback(async () => {
    setIsUpdating(true);
    try {
      if (pendingLlmSelection) {
        updateLlmSelection(pendingLlmSelection);
        setOriginalLlmSelection(pendingLlmSelection);
      }

      await clearPreProvisionedSession();
      ensurePreProvisionedSession();
      setUserLibraryChanged(false);
    } catch (error) {
      console.error("Failed to update settings:", error);
    } finally {
      setIsUpdating(false);
    }
  }, [
    pendingLlmSelection,
    updateLlmSelection,
    clearPreProvisionedSession,
    ensurePreProvisionedSession,
  ]);

  const existingPersona = getBuildUserPersona();
  const roleLabel = existingPersona?.workArea
    ? WORK_AREA_OPTIONS.find((o) => o.value === existingPersona.workArea)?.label
    : undefined;
  const levelLabel = existingPersona?.level
    ? LEVEL_OPTIONS.find((o) => o.value === existingPersona.level)?.label
    : undefined;
  const roleDescription = roleLabel
    ? levelLabel
      ? `${roleLabel}, ${levelLabel}`
      : roleLabel
    : "Not set";

  return (
    <div className="relative w-full h-full">
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
                disabled={!hasChanges || isUpdating}
                prominence="secondary"
                onClick={handleRestoreChanges}
              >
                Restore Changes
              </Button>
              <Button
                disabled={!hasChanges || isUpdating || isPreProvisioning}
                onClick={handleUpdate}
              >
                {isUpdating || isPreProvisioning ? "Updating..." : "Update"}
              </Button>
            </div>
          }
        />
        <SettingsLayouts.Body>
          <Section flexDirection="column" gap={2}>
            <Section
              flexDirection="column"
              alignItems="start"
              gap={0.5}
              height="fit"
            >
              <Card>
                <InputHorizontal
                  title="Your Role"
                  description={roleDescription}
                  center
                >
                  <button
                    type="button"
                    onClick={() => openUserInfoEditor()}
                    className="p-2 rounded-08 text-text-03 hover:bg-background-tint-02 transition-colors"
                  >
                    <SvgSettings className="w-5 h-5" />
                  </button>
                </InputHorizontal>
              </Card>
              <Card
                className={isUpdating || isPreProvisioning ? "opacity-50" : ""}
                title={
                  isUpdating || isPreProvisioning
                    ? "Please wait while your session is being provisioned"
                    : undefined
                }
              >
                <div
                  className={`w-full ${
                    isUpdating || isPreProvisioning ? "pointer-events-none" : ""
                  }`}
                >
                  <InputHorizontal
                    title="Default LLM"
                    description="Select the language model to craft with"
                    center
                    withLabel
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
                            const ModelIcon = getModelIcon(
                              pendingLlmSelection.provider
                            );
                            return <ModelIcon className="w-4 h-4" />;
                          })()}
                        <Text mainUiAction>{pendingLlmDisplayName}</Text>
                        <SvgChevronDown className="w-4 h-4 text-text-03" />
                      </button>
                    </BuildLLMPopover>
                  </InputHorizontal>
                </div>
              </Card>
              <Divider />
              <Card>
                <InputHorizontal
                  title="User Library"
                  description="Upload files to your personal library"
                  center
                >
                  <button
                    type="button"
                    onClick={() => setShowUserLibraryModal(true)}
                    className="p-2 rounded-08 text-text-03 hover:bg-background-tint-02 transition-colors"
                  >
                    <SvgFolder className="w-5 h-5" />
                  </button>
                </InputHorizontal>
              </Card>
              {canManageConnectors && (
                <Card>
                  <InputHorizontal
                    title="Connect your data"
                    description="Manage connectors on the admin page"
                    center
                  >
                    <button
                      type="button"
                      onClick={() => {
                        window.location.href = "/admin/indexing/status";
                      }}
                      className="p-2 rounded-08 text-text-03 hover:bg-background-tint-02 transition-colors"
                    >
                      <SvgChevronRight className="w-5 h-5" />
                    </button>
                  </InputHorizontal>
                </Card>
              )}
            </Section>
          </Section>
        </SettingsLayouts.Body>

        <UserLibraryModal
          open={showUserLibraryModal}
          onClose={() => setShowUserLibraryModal(false)}
          onChanges={() => setUserLibraryChanged(true)}
        />
      </SettingsLayouts.Root>
    </div>
  );
}
