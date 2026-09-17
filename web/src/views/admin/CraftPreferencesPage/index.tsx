"use client";

import { useCallback, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import useSWR, { mutate, useSWRConfig } from "swr";
import { Button, Card, Tag, Text } from "@opal/components";
import {
  IllustrationContent,
  InputVertical,
  SettingsLayouts,
  toast,
} from "@opal/layouts";
import { SvgArrowUpRight, SvgRefreshCw, SvgSimpleLoader } from "@opal/icons";
import SvgNoResult from "@opal/illustrations/no-result";
import { Section } from "@/layouts/general-layouts";
import { InputTextArea } from "@opal/components";
import SimpleCollapsible from "@/refresh-components/SimpleCollapsible";
import { ConfirmationModalLayout } from "@opal/layouts";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { useSettings } from "@/lib/settings/hooks";
import { toSettings } from "@/lib/settings/types";
import { updateAdminSettings } from "@/lib/settings/svc";
import useUnsavedChangesGuard from "@/hooks/useUnsavedChangesGuard";
import UnsavedChangesModal from "@/sections/modals/UnsavedChangesModal";
import { useAdminLLMProviders } from "@/lib/languageModels/hooks";
import { DefaultModel } from "@/lib/languageModels/types";
import {
  deleteDefaultCraftModel,
  setDefaultCraftModel,
} from "@/lib/languageModels/svc";
import { refreshLlmProviderCaches } from "@/lib/languageModels/cache";
import { BuildLlmSelection } from "@/app/craft/onboarding/constants";
import ModelPickerButton from "@/app/craft/components/ModelPickerButton";

const MAX_INSTRUCTIONS_LENGTH = 4000;

function BaseInstructionsPreview() {
  const t = useTranslations("admin.craftPreferences");
  const { data, error } = useSWR<{ content: string }>(
    SWR_KEYS.buildBaseInstructions,
    errorHandlingFetcher
  );

  if (error) {
    return (
      <Text font="secondary-body" color="text-03">
        {t("baseInstructions.loadError.description")}
      </Text>
    );
  }
  if (!data) {
    return (
      <div className="flex justify-center py-4">
        <SvgSimpleLoader className="h-5 w-5" />
      </div>
    );
  }
  return (
    <div className="rounded-lg border border-border-01 p-3 overflow-y-auto overflow-x-hidden bg-background-neutral-00 max-h-96">
      <pre className="m-0 whitespace-pre-wrap wrap-break-word font-mono text-xs leading-5 text-text-04">
        {data.content}
      </pre>
    </div>
  );
}

export default function CraftPreferencesPage() {
  const t = useTranslations("admin.craftPreferences");
  const settings = useSettings();
  const craftAvailable = settings?.onyx_craft_available === true;
  const savedInstructions = settings?.craft_instructions ?? "";

  const [draft, setDraft] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [resetConfirmOpen, setResetConfirmOpen] = useState(false);

  // null until the user edits — render the saved value until then.
  const value = draft ?? savedInstructions;
  const isDirty = value !== savedInstructions;
  const unsavedChanges = useUnsavedChangesGuard({ isDirty });

  async function save(instructions: string): Promise<boolean> {
    if (!settings) return false;
    setIsSaving(true);
    try {
      await updateAdminSettings({
        ...toSettings(settings),
        craft_instructions: instructions.trim() || null,
      });
      await mutate(SWR_KEYS.settings);
      setDraft(null);
      toast.success(t("saveSuccess.message"));
      return true;
    } catch (err) {
      console.error("Failed to save Craft instructions", err);
      toast.error(err instanceof Error ? err.message : t("saveError.message"));
      return false;
    } finally {
      setIsSaving(false);
    }
  }

  const { mutate: mutateScoped } = useSWRConfig();
  const {
    llmProviders,
    defaultCraft,
    defaultText,
    isLoading: isLoadingModels,
  } = useAdminLLMProviders();
  const [isSavingModel, setIsSavingModel] = useState(false);

  // Hidden models still resolve, so an admin can clear or replace a default
  // that was later hidden.
  const resolveSelection = useCallback(
    (model: DefaultModel | null): BuildLlmSelection | null => {
      if (!model || !llmProviders) return null;
      const provider = llmProviders.find(
        (candidate) => candidate.id === model.provider_id
      );
      const modelConfig = provider?.model_configurations.find(
        (candidate) => candidate.name === model.model_name
      );
      if (!provider || !modelConfig) return null;
      return {
        providerId: provider.id,
        providerName: provider.name ?? "",
        provider: provider.provider,
        modelName: model.model_name,
      };
    },
    [llmProviders]
  );

  // The explicitly configured Craft default — what Clear clears.
  const configuredSelection = useMemo(
    () => resolveSelection(defaultCraft),
    [resolveSelection, defaultCraft]
  );

  // What Craft actually runs today: the configured default, or the workspace
  // chat default it falls back to. Resolved here rather than inside the picker
  // so this admin's own remembered pick can't leak in as the workspace value.
  const inheritedSelection = useMemo(
    () => resolveSelection(defaultText),
    [resolveSelection, defaultText]
  );
  const effectiveSelection = configuredSelection ?? inheritedSelection;
  const isInherited = !configuredSelection && !!inheritedSelection;

  async function saveDefaultModel(selection: BuildLlmSelection) {
    setIsSavingModel(true);
    try {
      await setDefaultCraftModel(selection.providerId, selection.modelName);
      await refreshLlmProviderCaches(mutateScoped);
      toast.success(t("defaultModel.saveSuccess.message"));
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("defaultModel.saveError.message")
      );
    } finally {
      setIsSavingModel(false);
    }
  }

  async function resetDefaultModel() {
    setIsSavingModel(true);
    try {
      await deleteDefaultCraftModel();
      await refreshLlmProviderCaches(mutateScoped);
      toast.success(t("defaultModel.resetSuccess.message"));
    } catch (err) {
      toast.error(
        err instanceof Error
          ? err.message
          : t("defaultModel.resetError.message")
      );
    } finally {
      setIsSavingModel(false);
    }
  }

  const header = (
    <SettingsLayouts.Header
      icon={ADMIN_ROUTES.CRAFT_PREFERENCES.icon}
      title={t("header.title")}
      description={t("header.description")}
      rightChildren={
        craftAvailable && !settings.isLoading && !settings.error ? (
          <div className="flex items-start gap-2">
            <Button
              href="/craft"
              prominence="secondary"
              rightIcon={SvgArrowUpRight}
            >
              {t("tryInCraftButton.label")}
            </Button>
            <Button disabled={!isDirty || isSaving} onClick={() => save(value)}>
              {isSaving ? t("saveButton.savingLabel") : t("saveButton.label")}
            </Button>
          </div>
        ) : undefined
      }
      divider
    />
  );

  // useSettings returns a default object while loading (and on error), which
  // lacks onyx_craft_available — don't misreport Craft as unavailable.
  if (settings.isLoading || settings.error) {
    return (
      <SettingsLayouts.Root>
        {header}
        <SettingsLayouts.Body>
          {settings.error ? (
            <Text as="p" font="secondary-body" color="text-03">
              {t("settingsLoadError.description")}
            </Text>
          ) : (
            <div className="flex justify-center py-12">
              <SvgSimpleLoader className="h-6 w-6" />
            </div>
          )}
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>
    );
  }

  if (!craftAvailable) {
    return (
      <SettingsLayouts.Root>
        {header}
        <SettingsLayouts.Body>
          <IllustrationContent
            illustration={SvgNoResult}
            title={t("unavailable.title")}
            description={t("unavailable.description")}
          />
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>
    );
  }

  return (
    <SettingsLayouts.Root>
      {header}
      <SettingsLayouts.Body>
        <Card border="solid" rounding={4}>
          <Section alignItems="stretch" gap={1}>
            <InputVertical title={t("defaultModel.label")} withLabel>
              <div className="flex items-center gap-2">
                <ModelPickerButton
                  selection={effectiveSelection}
                  onChange={saveDefaultModel}
                  disabled={isSavingModel}
                  fallbackToDefault={false}
                  persistSelection={false}
                  loading={isLoadingModels}
                  placeholder={t("defaultModel.placeholder")}
                />
                {isInherited && (
                  <Tag title={t("defaultModel.inheritedTag.label")} />
                )}
                {configuredSelection && (
                  <Button
                    icon={SvgRefreshCw}
                    variant="danger"
                    prominence="tertiary"
                    size="sm"
                    disabled={isSavingModel}
                    onClick={resetDefaultModel}
                  >
                    {t("defaultModel.clearButton.label")}
                  </Button>
                )}
              </div>
              <Text font="secondary-body" color="text-03">
                {t("defaultModel.help.description")}
              </Text>
            </InputVertical>
          </Section>
        </Card>

        <Card border="solid" rounding={4}>
          <Section alignItems="stretch" gap={1}>
            <InputVertical
              title={t("instructions.label")}
              topRight={t("instructions.charCount.label", {
                count: value.length,
                max: MAX_INSTRUCTIONS_LENGTH,
              })}
              withLabel
            >
              <InputTextArea
                value={value}
                onChange={(event) => setDraft(event.target.value)}
                placeholder={t("instructions.placeholder")}
                rows={8}
                autoResize
                maxRows={24}
                maxLength={MAX_INSTRUCTIONS_LENGTH}
              />
              <div className="w-full flex items-center justify-between gap-4">
                <Text font="secondary-body" color="text-03">
                  {t("instructions.help.description")}
                </Text>
                {savedInstructions && (
                  <Button
                    icon={SvgRefreshCw}
                    variant="danger"
                    prominence="tertiary"
                    size="sm"
                    disabled={isSaving}
                    onClick={() => setResetConfirmOpen(true)}
                  >
                    {t("resetButton.label")}
                  </Button>
                )}
              </div>
            </InputVertical>
          </Section>
        </Card>

        <SimpleCollapsible defaultOpen={false}>
          <SimpleCollapsible.Header
            title={t("baseInstructions.title")}
            description={t("baseInstructions.description")}
          />
          <SimpleCollapsible.Content>
            <BaseInstructionsPreview />
          </SimpleCollapsible.Content>
        </SimpleCollapsible>
      </SettingsLayouts.Body>

      {resetConfirmOpen && (
        <ConfirmationModalLayout
          icon={ADMIN_ROUTES.CRAFT_PREFERENCES.icon}
          title={t("resetModal.header.title")}
          onClose={isSaving ? undefined : () => setResetConfirmOpen(false)}
          submit={
            <Button
              variant="danger"
              disabled={isSaving}
              onClick={async () => {
                if (await save("")) {
                  setResetConfirmOpen(false);
                }
              }}
            >
              {isSaving
                ? t("resetModal.resettingLabel")
                : t("resetModal.submitButton.label")}
            </Button>
          }
        >
          {t("resetModal.body.description")}
        </ConfirmationModalLayout>
      )}
      <UnsavedChangesModal
        open={unsavedChanges.confirmationOpen}
        onCancel={unsavedChanges.cancelLeave}
        onDiscard={unsavedChanges.discardAndLeave}
      />
    </SettingsLayouts.Root>
  );
}
