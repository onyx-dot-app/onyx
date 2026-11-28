"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { InputHorizontal, Section, toast } from "@opal/layouts";
import {
  Button,
  InputSingleSelect,
  InputSwitch,
  InputTextArea,
  InputTypeIn,
  Text,
  Tooltip,
} from "@opal/components";
import { SvgMinusCircle } from "@opal/icons";
import { useUser } from "@/providers/UserProvider";
import { MemoryItem } from "@/lib/types";
import useUserPersonalization from "@/hooks/useUserPersonalization";
import usePromptShortcuts from "@/hooks/usePromptShortcuts";
import { InputPrompt } from "@/app/app/types";
import CharacterCount from "@/refresh-components/CharacterCount";
import Memories from "@/sections/settings/Memories";
import { SimpleModelSelector } from "@/lib/languageModels/components";
import { structureValue } from "@/lib/languageModels/utils";
import {
  filterModelConfigurations,
  findDefaultModelDisplayName,
  findLlmOptionById,
  findModelConfigId,
} from "@/lib/languageModels/options";
import { useLanguageModels } from "@/lib/languageModels/hooks";
import { useLlmManager } from "@/lib/hooks";
import { useTierAtLeast } from "@/lib/tiers/hooks";
import { Tier } from "@/lib/tiers/types";
import { useIsSearchModeAvailable, useSettings } from "@/lib/settings/hooks";
import {
  ALL_REASONING_STOPS,
  PaneSlider,
  REASONING_STOP_LABEL_KEYS,
  UNSET_REASONING_STOP,
  reasoningStopIndex,
} from "@/sections/model-selector/setting-controls";
import SettingsSection from "@/views/settings/SettingsSection";

interface LocalShortcut extends InputPrompt {
  isNew: boolean;
}

function PromptShortcuts() {
  const t = useTranslations("settings");
  const { promptShortcuts, isLoading, error, refresh } = usePromptShortcuts();
  const [shortcuts, setShortcuts] = useState<LocalShortcut[]>([]);
  const [isInitialLoad, setIsInitialLoad] = useState(true);

  // Initialize shortcuts when input prompts are loaded
  useEffect(() => {
    if (isLoading || error) return;

    // Convert InputPrompt[] to LocalShortcut[] with isNew: false for existing items
    // Sort by id to maintain stable ordering when editing
    const existingShortcuts: LocalShortcut[] = promptShortcuts
      .map((shortcut) => ({
        ...shortcut,
        isNew: false,
      }))
      .sort((a, b) => a.id - b.id);

    // Always ensure there's at least one empty row
    setShortcuts([
      ...existingShortcuts,
      {
        id: Date.now(),
        prompt: "",
        content: "",
        active: true,
        is_public: false,
        isNew: true,
      },
    ]);
    setIsInitialLoad(false);
  }, [promptShortcuts, isLoading, error]);

  // Show error popup if fetch fails
  useEffect(() => {
    if (!error) return;
    toast.error(t("promptShortcuts.toasts.loadFailed"));
  }, [error, t]);

  const handleUpdateShortcut = useCallback(
    (index: number, field: "prompt" | "content", value: string) => {
      setShortcuts((prev) => {
        const next = prev.map((shortcut, i) =>
          i === index ? { ...shortcut, [field]: value } : shortcut
        );

        const isEmptyNew = (s: LocalShortcut) =>
          s.isNew && !s.prompt.trim() && !s.content.trim();

        const emptyCount = next.filter(isEmptyNew).length;

        if (emptyCount === 0) {
          return [
            ...next,
            {
              id: Date.now(),
              prompt: "",
              content: "",
              active: true,
              is_public: false,
              isNew: true,
            },
          ];
        }

        if (emptyCount > 1) {
          const userRow = next[index];
          const userRowEmpty = userRow !== undefined && isEmptyNew(userRow);
          let keepIndex = -1;
          if (userRowEmpty) {
            keepIndex = index;
          } else {
            for (let i = next.length - 1; i >= 0; i--) {
              const row = next[i];
              if (row !== undefined && isEmptyNew(row)) {
                keepIndex = i;
                break;
              }
            }
          }
          return next.filter((s, i) => !isEmptyNew(s) || i === keepIndex);
        }

        return next;
      });
    },
    []
  );

  const handleRemoveShortcut = useCallback(
    async (index: number) => {
      const shortcut = shortcuts[index];
      if (!shortcut) return;

      // If it's a new shortcut, just remove from state
      if (shortcut.isNew) {
        setShortcuts((prev) => prev.filter((_, i) => i !== index));
        return;
      }

      // Otherwise, delete from backend
      try {
        const response = await fetch(`/api/input_prompt/${shortcut.id}`, {
          method: "DELETE",
        });

        if (response.ok) {
          setShortcuts((prev) => prev.filter((_, i) => i !== index));
          await refresh();
        } else {
          throw new Error("Failed to delete shortcut");
        }
      } catch (error) {
        toast.error(t("promptShortcuts.toasts.deleteFailed"));
      }
    },
    [shortcuts, refresh, t]
  );

  const handleSaveShortcut = useCallback(
    async (index: number) => {
      const shortcut = shortcuts[index];
      if (!shortcut || !shortcut.prompt.trim() || !shortcut.content.trim()) {
        toast.error(t("promptShortcuts.toasts.bothRequired"));
        return;
      }

      try {
        if (shortcut.isNew) {
          // Create new shortcut
          const response = await fetch("/api/input_prompt", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              prompt: shortcut.prompt,
              content: shortcut.content,
              active: true,
              is_public: false,
            }),
          });

          if (response.ok) {
            await refresh();
          } else {
            throw new Error("Failed to create shortcut");
          }
        } else {
          // Update existing shortcut
          const response = await fetch(`/api/input_prompt/${shortcut.id}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              prompt: shortcut.prompt,
              content: shortcut.content,
              active: true,
              is_public: false,
            }),
          });

          if (response.ok) {
            await refresh();
          } else {
            throw new Error("Failed to update shortcut");
          }
        }
      } catch (error) {
        toast.error(t("promptShortcuts.toasts.saveFailed"));
      }
    },
    [shortcuts, refresh, t]
  );

  const handleBlurShortcut = useCallback(
    async (index: number) => {
      const shortcut = shortcuts[index];
      if (!shortcut) return;

      const hasPrompt = shortcut.prompt.trim();
      const hasContent = shortcut.content.trim();

      // Both fields are filled - save/update the shortcut
      if (hasPrompt && hasContent) {
        await handleSaveShortcut(index);
      }
      // For existing shortcuts with incomplete fields, error state will be shown in UI
      // User must use the delete button to remove them
    },
    [shortcuts, handleSaveShortcut]
  );

  return (
    <>
      {shortcuts.length > 0 && (
        <Section gap={3}>
          {shortcuts.map((shortcut, index) => {
            const isEmpty = !shortcut.prompt.trim() && !shortcut.content.trim();
            const isExisting = !shortcut.isNew;
            const hasPrompt = shortcut.prompt.trim();
            const hasContent = shortcut.content.trim();

            // Show error for existing shortcuts with incomplete fields
            // (either one field empty or both fields empty)
            const showPromptError = isExisting && !hasPrompt;
            const showContentError = isExisting && !hasContent;

            return (
              <Section
                key={shortcut.id}
                flexDirection="row"
                alignItems="start"
                height="fit"
                gap={1}
              >
                <Section height="fit" gap={1}>
                  <InputTypeIn
                    leftChildren={
                      <Text font="main-ui-body" color="text-02">
                        /
                      </Text>
                    }
                    placeholder={t("promptShortcuts.row.promptPlaceholder")}
                    value={shortcut.prompt}
                    onChange={(e) =>
                      handleUpdateShortcut(index, "prompt", e.target.value)
                    }
                    onBlur={
                      shortcut.is_public
                        ? undefined
                        : () => void handleBlurShortcut(index)
                    }
                    variant={
                      shortcut.is_public
                        ? "readOnly"
                        : showPromptError
                          ? "error"
                          : undefined
                    }
                  />
                  <InputTextArea
                    placeholder={t("promptShortcuts.row.contentPlaceholder")}
                    value={shortcut.content}
                    onChange={(e) =>
                      handleUpdateShortcut(index, "content", e.target.value)
                    }
                    onBlur={
                      shortcut.is_public
                        ? undefined
                        : () => void handleBlurShortcut(index)
                    }
                    variant={
                      shortcut.is_public
                        ? "readOnly"
                        : showContentError
                          ? "error"
                          : undefined
                    }
                    rows={3}
                  />
                </Section>
                <Button
                  disabled={(shortcut.isNew && isEmpty) || shortcut.is_public}
                  icon={SvgMinusCircle}
                  onClick={() => void handleRemoveShortcut(index)}
                  prominence="tertiary"
                  aria-label={t("promptShortcuts.row.removeAriaLabel")}
                  tooltip={
                    shortcut.is_public
                      ? t("promptShortcuts.row.publicTooltip")
                      : undefined
                  }
                />
              </Section>
            );
          })}
        </Section>
      )}
    </>
  );
}

export default function ChatPreferencesSettings() {
  const t = useTranslations("settings");
  const tInputSelect = useTranslations("common.inputSelect");
  const tModelSelector = useTranslations("chat.modelSelector");
  const { user, updatePreferences, updateUserPersonalization } = useUser();
  const businessTier = useTierAtLeast(Tier.BUSINESS);
  const searchUiEnabled = useIsSearchModeAvailable();
  const llmManager = useLlmManager();
  const {
    personalizationValues,
    updateUserPreferences,
    toggleUseMemories,
    toggleEnableMemoryTool,
    handleSavePersonalization,
  } = useUserPersonalization(user, updateUserPersonalization, {
    onError: () => toast.error(t("memory.toasts.saveFailed")),
  });

  const handleSaveMemories = useCallback(
    async (newMemories: MemoryItem[]): Promise<boolean> => {
      const result = await handleSavePersonalization(
        { memories: newMemories },
        true
      );
      return !!result;
    },
    [handleSavePersonalization]
  );

  const [draftVoicePlaybackSpeed, setDraftVoicePlaybackSpeed] = useState(
    user?.preferences.voice_playback_speed ?? 1
  );

  useEffect(() => {
    setDraftVoicePlaybackSpeed(user?.preferences.voice_playback_speed ?? 1);
  }, [user?.preferences.voice_playback_speed]);

  const settings = useSettings();
  const { defaultText } = useLanguageModels();
  // The user's default as a configuration id; null means the global default.
  const defaultModelConfigId = user?.preferences?.default_model
    ? findModelConfigId(
        llmManager.llmProviders,
        llmManager.currentLlm.provider,
        llmManager.currentLlm.modelName
      )
    : null;
  const userTemperatureDefault = user?.preferences.temperature_default ?? null;
  const userEffortDefault = user?.preferences.reasoning_effort_default ?? null;
  // 0 mirrors the backend GEN_AI_TEMPERATURE fallback an untouched chat
  // actually runs with, so the parked slider never overstates the default.
  const [draftTemperature, setDraftTemperature] = useState(
    userTemperatureDefault ?? 0
  );
  const [draftEffortStop, setDraftEffortStop] = useState(() => {
    const stop = reasoningStopIndex(userEffortDefault);
    return stop >= 0 ? stop : UNSET_REASONING_STOP;
  });

  useEffect(() => {
    if (userTemperatureDefault != null) {
      setDraftTemperature(userTemperatureDefault);
    }
  }, [userTemperatureDefault]);
  useEffect(() => {
    const stop = reasoningStopIndex(userEffortDefault);
    if (stop >= 0) setDraftEffortStop(stop);
  }, [userEffortDefault]);

  return (
    <Section gap={8}>
      <SettingsSection title={t("personalPreferences.title")}>
        <Section gap={1} alignItems="start">
          <Text font="secondary-body" color="text-03" as="p">
            {t("personalPreferences.description", {
              appName: settings.appName,
            })}
          </Text>
          <InputTextArea
            aria-label={t("personalPreferences.title")}
            placeholder={t("personalPreferences.placeholder")}
            value={personalizationValues.user_preferences}
            onChange={(e) => updateUserPreferences(e.target.value)}
            onBlur={() =>
              void handleSavePersonalization({
                user_preferences: personalizationValues.user_preferences,
              })
            }
            rows={4}
            maxRows={10}
            autoResize
            maxLength={500}
          />
          <CharacterCount
            value={personalizationValues.user_preferences || ""}
            limit={500}
          />
        </Section>
      </SettingsSection>

      <SettingsSection title={t("modelPreferences.title")}>
        <InputHorizontal
          title={t("chats.defaultModel.title")}
          description={t("chats.defaultModel.description", {
            appName: settings.appName,
          })}
          withLabel
          fillInput
        >
          <SimpleModelSelector
            aria-label={t("chats.defaultModel.title")}
            nullable
            globalDefault={{
              description: findDefaultModelDisplayName(
                llmManager.llmProviders,
                defaultText
              ),
            }}
            providers={filterModelConfigurations(
              llmManager.llmProviders ?? [],
              { keep: defaultModelConfigId }
            )}
            value={defaultModelConfigId}
            grouped={!settings.hide_provider_grouping}
            onChange={(modelConfigurationId) => {
              const opt = findLlmOptionById(
                llmManager.llmProviders,
                modelConfigurationId
              );
              if (modelConfigurationId === null || opt === null) {
                void updatePreferences(
                  { default_model: null },
                  "/api/user/default-model"
                );
                return;
              }
              llmManager.updateCurrentLlm({
                name: opt.name,
                provider: opt.provider,
                modelName: opt.modelName,
                modelConfigurationId,
              });
              void updatePreferences(
                {
                  default_model: structureValue(
                    opt.name,
                    opt.provider,
                    opt.modelName,
                    modelConfigurationId
                  ),
                },
                "/api/user/default-model"
              );
            }}
          />
        </InputHorizontal>

        {(user?.preferences?.temperature_override_enabled ?? true) && (
          <InputHorizontal
            title={t("chats.defaultTemperature.title")}
            description={t("chats.defaultTemperature.description")}
            withLabel
          >
            <Section flexDirection="row" width="fit" height="auto" gap={3}>
              <Section width={8} height="auto">
                <PaneSlider
                  compact
                  value={draftTemperature}
                  min={0}
                  max={2}
                  step={0.1}
                  onValueChange={setDraftTemperature}
                  onValueCommit={(value) => {
                    void updatePreferences(
                      { temperature_default: value },
                      "/api/temperature-default"
                    );
                  }}
                />
              </Section>
              <Section width={4} height="auto" alignItems="end">
                <Text
                  as="p"
                  font="secondary-mono"
                  color="text-04"
                  wordWrap="whitespace-nowrap"
                >
                  {draftTemperature.toFixed(1)}
                </Text>
              </Section>
            </Section>
          </InputHorizontal>
        )}

        {!settings.isLoading &&
          (settings.reasoning_override_enabled ?? true) && (
            <InputHorizontal
              title={t("chats.defaultReasoningLevel.title")}
              description={t("chats.defaultReasoningLevel.description")}
              withLabel
            >
              <Section flexDirection="row" width="fit" height="auto" gap={3}>
                <Section width={8} height="auto">
                  <PaneSlider
                    compact
                    value={draftEffortStop}
                    min={0}
                    max={ALL_REASONING_STOPS.length - 1}
                    step={1}
                    onValueChange={setDraftEffortStop}
                    onValueCommit={(value) => {
                      void updatePreferences(
                        {
                          reasoning_effort_default:
                            ALL_REASONING_STOPS[value] ?? null,
                        },
                        "/api/reasoning-effort-default"
                      );
                    }}
                  />
                </Section>
                <Section width={4} height="auto" alignItems="end">
                  <Text
                    as="p"
                    font="secondary-mono"
                    color="text-04"
                    wordWrap="whitespace-nowrap"
                  >
                    {tModelSelector(
                      REASONING_STOP_LABEL_KEYS[
                        ALL_REASONING_STOPS[draftEffortStop] ?? "medium"
                      ]
                    )}
                  </Text>
                </Section>
              </Section>
            </InputHorizontal>
          )}
      </SettingsSection>

      <SettingsSection title={t("memory.title")}>
        <InputHorizontal
          title={t("memory.referenceStoredMemories.title")}
          description={t("memory.referenceStoredMemories.description", {
            appName: settings.appName,
          })}
          withLabel
        >
          <InputSwitch
            checked={personalizationValues.use_memories}
            onCheckedChange={(checked) => {
              toggleUseMemories(checked);
              void handleSavePersonalization({ use_memories: checked });
            }}
          />
        </InputHorizontal>
        <InputHorizontal
          title={t("memory.updateMemories.title")}
          description={t("memory.updateMemories.description", {
            appName: settings.appName,
          })}
          withLabel
        >
          <InputSwitch
            checked={personalizationValues.enable_memory_tool}
            onCheckedChange={(checked) => {
              toggleEnableMemoryTool(checked);
              void handleSavePersonalization({
                enable_memory_tool: checked,
              });
            }}
          />
        </InputHorizontal>

        {(personalizationValues.use_memories ||
          personalizationValues.enable_memory_tool ||
          personalizationValues.memories.length > 0) && (
          <Memories
            memories={personalizationValues.memories}
            onSaveMemories={handleSaveMemories}
          />
        )}
      </SettingsSection>

      <SettingsSection title={t("interactions.title")}>
        <InputHorizontal
          title={t("chats.sendBehavior.title")}
          description={t("chats.sendBehavior.description")}
          withLabel
        >
          <InputSingleSelect
            placeholder={t("chats.sendBehavior.title")}
            aria-label={t("chats.sendBehavior.title")}
            defaultOption="send"
            value={user?.preferences.interrupt_on_send ? "interrupt" : "send"}
            options={[
              { value: "send", title: t("chats.sendBehavior.afterStep") },
              {
                value: "interrupt",
                title: t("chats.sendBehavior.interrupt"),
              },
            ]}
            onValueChange={(value) => {
              const interruptOnSend = value === "interrupt";
              void updatePreferences(
                { interrupt_on_send: interruptOnSend },
                `/api/interrupt-on-send?interrupt_on_send=${interruptOnSend}`
              );
            }}
          />
        </InputHorizontal>

        <InputHorizontal
          title={t("chats.collapseLargePastes.title")}
          description={t("chats.collapseLargePastes.description")}
          withLabel
        >
          <InputSwitch
            checked={user?.preferences?.paste_as_tile ?? true}
            onCheckedChange={(checked) => {
              void updatePreferences(
                { paste_as_tile: checked },
                `/api/paste-as-tile?paste_as_tile=${checked}`
              );
            }}
          />
        </InputHorizontal>

        <InputHorizontal
          title={t("promptShortcuts.toggle.title")}
          description={t("promptShortcuts.toggle.description")}
          withLabel
        >
          <InputSwitch
            checked={user?.preferences?.shortcut_enabled}
            onCheckedChange={(checked) => {
              void updatePreferences(
                { shortcut_enabled: checked },
                `/api/shortcut-enabled?shortcut_enabled=${checked}`
              );
            }}
          />
        </InputHorizontal>

        {user?.preferences?.shortcut_enabled && <PromptShortcuts />}

        {businessTier && (
          <Tooltip
            tooltip={
              searchUiEnabled
                ? undefined
                : t("chats.defaultAppMode.disabledTooltip")
            }
            side="top"
          >
            <InputHorizontal
              title={t("chats.defaultAppMode.title")}
              description={t("chats.defaultAppMode.description")}
              center
              disabled={!searchUiEnabled}
              withLabel
              fillInput
            >
              <InputSingleSelect
                value={user?.preferences.default_app_mode ?? "CHAT"}
                onValueChange={(value) => {
                  // SAFETY: the options are "CHAT" and "SEARCH".
                  const mode = value as "CHAT" | "SEARCH";
                  void updatePreferences(
                    { default_app_mode: mode },
                    "/api/user/default-app-mode"
                  );
                }}
                disabled={!searchUiEnabled}
                defaultOption="CHAT"
                placeholder={tInputSelect("placeholder.fallback")}
                aria-label={t("chats.defaultAppMode.title")}
                options={[
                  {
                    value: "CHAT",
                    title: t("chats.defaultAppMode.chatOption"),
                  },
                  {
                    value: "SEARCH",
                    title: t("chats.defaultAppMode.searchOption"),
                  },
                ]}
              />
            </InputHorizontal>
          </Tooltip>
        )}

        {settings.chrome_browser_available && (
          <InputHorizontal
            title={t("chats.defaultBrowser.title")}
            description={t("chats.defaultBrowser.description")}
            center
            withLabel
            fillInput
          >
            <InputSingleSelect
              value={user?.preferences.default_browser ?? "SANDBOX"}
              onValueChange={(value) => {
                // SAFETY: the options are "SANDBOX" and "CHROME".
                const browser = value as "SANDBOX" | "CHROME";
                void updatePreferences(
                  { default_browser: browser },
                  "/api/user/default-browser"
                );
              }}
              defaultOption="SANDBOX"
              placeholder={tInputSelect("placeholder.fallback")}
              aria-label={t("chats.defaultBrowser.title")}
              options={[
                {
                  value: "SANDBOX",
                  title: t("chats.defaultBrowser.sandboxOption"),
                },
                {
                  value: "CHROME",
                  title: t("chats.defaultBrowser.chromeOption"),
                },
              ]}
            />
          </InputHorizontal>
        )}
      </SettingsSection>

      <SettingsSection title={t("voice.title")}>
        <InputHorizontal
          title={t("voice.autoSend.title")}
          description={t("voice.autoSend.description")}
          withLabel
        >
          <InputSwitch
            checked={user?.preferences.voice_auto_send ?? false}
            onCheckedChange={(checked) => {
              void updatePreferences(
                { voice_auto_send: checked },
                "/api/voice/settings",
                { auto_send: checked }
              );
            }}
          />
        </InputHorizontal>

        <InputHorizontal
          title={t("voice.autoPlayback.title")}
          description={t("voice.autoPlayback.description")}
          withLabel
        >
          <InputSwitch
            checked={user?.preferences.voice_auto_playback ?? false}
            onCheckedChange={(checked) => {
              void updatePreferences(
                { voice_auto_playback: checked },
                "/api/voice/settings",
                { auto_playback: checked }
              );
            }}
          />
        </InputHorizontal>

        <InputHorizontal
          title={t("voice.playbackSpeed.title")}
          description={t("voice.playbackSpeed.description")}
          withLabel
        >
          <Section flexDirection="row" width="fit" height="auto" gap={3}>
            <Section width={8} height="auto">
              <PaneSlider
                compact
                value={draftVoicePlaybackSpeed}
                min={0.5}
                max={2}
                step={0.1}
                onValueChange={setDraftVoicePlaybackSpeed}
                onValueCommit={(value) => {
                  void updatePreferences(
                    { voice_playback_speed: value },
                    "/api/voice/settings",
                    { playback_speed: value }
                  );
                }}
              />
            </Section>
            <Section width={4} height="auto" alignItems="end">
              <Text
                as="p"
                font="secondary-mono"
                color="text-04"
                wordWrap="whitespace-nowrap"
              >
                {t("voice.playbackSpeed.value", {
                  speed: draftVoicePlaybackSpeed.toFixed(1),
                })}
              </Text>
            </Section>
          </Section>
        </InputHorizontal>
      </SettingsSection>
    </Section>
  );
}
