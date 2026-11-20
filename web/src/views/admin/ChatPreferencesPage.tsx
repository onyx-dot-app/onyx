"use client";

import { useNavigation } from "@opal/navigation";
import { parseErrorDetail } from "@/lib/fetcher";

import { useBetaTag, usePlans, useTierAtLeast } from "@/lib/tiers/hooks";
import { getSourceMetadata } from "@/lib/connectors/utils";
import { useAdminRouteTitle } from "@/lib/adminNavLabels";
import { markdown } from "@opal/utils";
import React, { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Formik, Form } from "formik";
import { mutate } from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import { SettingsLayouts, toast, Section } from "@opal/layouts";
import { Collapsible } from "@opal/components";
import InputTextAreaField from "@/refresh-components/form/InputTextAreaField";
import { InputTextArea, InputTypeIn } from "@opal/components";
import { SvgAddLines, SvgExternalLink, SvgRefreshCw } from "@opal/icons";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import {
  Content,
  ContentAction,
  InputHorizontal,
  InputVertical,
} from "@opal/layouts";
import { useSettings } from "@/lib/settings/hooks";
import useCCPairs from "@/hooks/useCCPairs";
import { Settings, toSettings } from "@/lib/settings/types";
import { LanguageSelect } from "@/lib/app/components";
import { useAvailableTools } from "@/lib/tools/hooks";
import {
  SEARCH_TOOL_ID,
  IMAGE_GENERATION_TOOL_ID,
  WEB_SEARCH_TOOL_ID,
  PYTHON_TOOL_ID,
  OPEN_URL_TOOL_ID,
} from "@/lib/tools/constants";
import {
  EmptyMessageCard,
  Button,
  Divider,
  Text,
  Card,
  MessageCard,
} from "@opal/components";
import { Modal } from "@opal/components";
import { InputSwitch } from "@opal/components";
import { Disabled, Hoverable } from "@opal/core";
import { Tier } from "@/lib/tiers/types";
import {
  ChatNamingModelSetting,
  SearchDecisionModelSetting,
} from "@/views/admin/ChatTaskModelSettings";

import { useDefaultAssistantConfiguration } from "@/lib/agents/hooks";

const route = ADMIN_ROUTES.CHAT_PREFERENCES;

type FileLimitFieldName =
  | "user_file_max_upload_size_mb"
  | "file_token_count_threshold_k";

interface NumericLimitFieldProps {
  name: FileLimitFieldName;
  initialValue: string;
  defaultValue: string;
  saveSettings: (updates: Partial<Settings>) => Promise<void>;
  maxValue?: number;
  allowZero?: boolean;
}

function NumericLimitField({
  name,
  initialValue: initialValueProp,
  defaultValue,
  saveSettings,
  maxValue,
  allowZero = false,
}: NumericLimitFieldProps) {
  const t = useTranslations("admin.chatPreferences");
  const [value, setValue] = useState(initialValueProp);
  const savedValue = useRef(initialValueProp);
  const restoringRef = useRef(false);

  const parsed = parseInt(value, 10);
  const isOverMax =
    maxValue !== undefined && !isNaN(parsed) && parsed > maxValue;

  const handleRestore = () => {
    restoringRef.current = true;
    savedValue.current = defaultValue;
    setValue(defaultValue);
    void saveSettings({ [name]: parseInt(defaultValue, 10) });
  };

  const handleBlur = () => {
    // The restore button triggers a blur — skip since handleRestore already saved.
    if (restoringRef.current) {
      restoringRef.current = false;
      return;
    }

    const parsed = parseInt(value, 10);
    const isValid = !isNaN(parsed) && (allowZero ? parsed >= 0 : parsed > 0);

    // Revert invalid input (empty, NaN, negative).
    if (!isValid) {
      if (allowZero) {
        // Empty/invalid means "no limit" — persist 0 and clear the field.
        setValue("");
        void saveSettings({ [name]: 0 });
        savedValue.current = "";
      } else {
        setValue(savedValue.current);
      }
      return;
    }

    // Block save when the value exceeds the hard ceiling.
    if (maxValue !== undefined && parsed > maxValue) {
      return;
    }

    // For allowZero fields, 0 means "no limit" — clear the display
    // so the "No limit" placeholder is visible, but still persist 0.
    if (allowZero && parsed === 0) {
      setValue("");
      if (savedValue.current !== "") {
        void saveSettings({ [name]: 0 });
        savedValue.current = "";
      }
      return;
    }

    const normalizedDisplay = String(parsed);

    // Update the display to the canonical form (e.g. strip leading zeros).
    if (value !== normalizedDisplay) {
      setValue(normalizedDisplay);
    }

    // Persist only when the value actually changed.
    if (normalizedDisplay !== savedValue.current) {
      void saveSettings({ [name]: parsed });
      savedValue.current = normalizedDisplay;
    }
  };

  return (
    <Hoverable.Root group="numericLimit" width="full">
      <InputTypeIn
        inputMode="numeric"
        pattern="[0-9]*"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder={
          allowZero
            ? t("fileLimits.noLimit.placeholder")
            : t("fileLimits.default.placeholder", { value: defaultValue })
        }
        variant={isOverMax ? "error" : undefined}
        rightChildren={
          (value || "") !== defaultValue ? (
            <Hoverable.Item group="numericLimit" variant="appear-on-hover">
              <Button
                icon={SvgRefreshCw}
                tooltip={t("fileLimits.restoreDefault.tooltip")}
                prominence="internal"
                onClick={handleRestore}
              />
            </Hoverable.Item>
          ) : undefined
        }
        onBlur={handleBlur}
      />
    </Hoverable.Root>
  );
}

interface FileSizeLimitFieldsProps {
  saveSettings: (updates: Partial<Settings>) => Promise<void>;
  initialUploadSizeMb: string;
  defaultUploadSizeMb: string;
  initialTokenThresholdK: string;
  defaultTokenThresholdK: string;
  maxAllowedUploadSizeMb?: number;
}

function FileSizeLimitFields({
  saveSettings,
  initialUploadSizeMb,
  defaultUploadSizeMb,
  initialTokenThresholdK,
  defaultTokenThresholdK,
  maxAllowedUploadSizeMb,
}: FileSizeLimitFieldsProps) {
  const t = useTranslations("admin.chatPreferences");

  return (
    <div className="flex gap-4 w-full items-start pt-2">
      <div className="flex-1">
        <InputVertical
          title={t("fileLimits.size.title")}
          suffix={t("fileLimits.size.suffix")}
          subDescription={
            maxAllowedUploadSizeMb
              ? t("fileLimits.size.maxDescription", {
                  // String, not number, so ICU does not add digit grouping.
                  max: String(maxAllowedUploadSizeMb),
                })
              : undefined
          }
          withLabel
        >
          <NumericLimitField
            name="user_file_max_upload_size_mb"
            initialValue={initialUploadSizeMb}
            defaultValue={defaultUploadSizeMb}
            saveSettings={saveSettings}
            maxValue={maxAllowedUploadSizeMb}
          />
        </InputVertical>
      </div>
      <div className="flex-1">
        <InputVertical
          title={t("fileLimits.tokens.title")}
          withLabel
          suffix={t("fileLimits.tokens.suffix")}
        >
          <NumericLimitField
            name="file_token_count_threshold_k"
            initialValue={initialTokenThresholdK}
            defaultValue={defaultTokenThresholdK}
            saveSettings={saveSettings}
            allowZero
          />
        </InputVertical>
      </div>
    </div>
  );
}

export default function ChatPreferencesPage() {
  const t = useTranslations("admin.chatPreferences");
  const plans = usePlans();
  const betaTag = useBetaTag();
  const adminRouteTitle = useAdminRouteTitle();
  const navigation = useNavigation();
  const settings = useSettings();
  const s = settings;
  // Search Mode toggle is Business+.
  const businessTier = useTierAtLeast(Tier.BUSINESS);

  // Local state for text fields (save-on-blur)
  const [companyName, setCompanyName] = useState(s.company_name ?? "");
  const [companyDescription, setCompanyDescription] = useState(
    s.company_description ?? ""
  );
  const savedCompanyName = useRef(companyName);
  const savedCompanyDescription = useRef(companyDescription);

  // Re-sync local state when settings change externally (e.g. another admin),
  // but only when there's no in-progress edit (local matches last-saved value).
  useEffect(() => {
    const incoming = s.company_name ?? "";
    if (companyName === savedCompanyName.current && incoming !== companyName) {
      setCompanyName(incoming);
      savedCompanyName.current = incoming;
    }
  }, [s.company_name]);

  useEffect(() => {
    const incoming = s.company_description ?? "";
    if (
      companyDescription === savedCompanyDescription.current &&
      incoming !== companyDescription
    ) {
      setCompanyDescription(incoming);
      savedCompanyDescription.current = incoming;
    }
  }, [s.company_description]);

  // Tools availability
  const { tools: availableTools } = useAvailableTools();
  const { vectorDbEnabled } = settings;

  const searchTool = availableTools.find(
    (t) => t.in_code_tool_id === SEARCH_TOOL_ID
  );
  const imageGenTool = availableTools.find(
    (t) => t.in_code_tool_id === IMAGE_GENERATION_TOOL_ID
  );
  const webSearchTool = availableTools.find(
    (t) => t.in_code_tool_id === WEB_SEARCH_TOOL_ID
  );
  const openURLTool = availableTools.find(
    (t) => t.in_code_tool_id === OPEN_URL_TOOL_ID
  );
  const codeInterpreterTool = availableTools.find(
    (t) => t.in_code_tool_id === PYTHON_TOOL_ID
  );

  // Connectors
  const { ccPairs } = useCCPairs();
  const uniqueSources = Array.from(new Set(ccPairs.map((p) => p.source)));

  // Default agent configuration (system prompt)
  const {
    data: defaultAgentConfig,
    mutate: mutateDefaultAgent,
    updateTools,
  } = useDefaultAssistantConfiguration();
  const enabledToolIds = defaultAgentConfig?.tool_ids ?? [];
  const isToolEnabled = (toolDbId: number) => enabledToolIds.includes(toolDbId);
  const toggleTools = async (toolDbIds: number[], enabled: boolean) => {
    try {
      await updateTools(toolDbIds, enabled);
    } catch {
      toast.error(t("toasts.toolsUpdateFailed"));
    }
  };
  const toggleTool = (toolDbId: number, enabled: boolean) => {
    void toggleTools([toolDbId], enabled);
  };

  // System prompt modal state
  const [systemPromptModalOpen, setSystemPromptModalOpen] = useState(false);

  const saveSettings = useCallback(
    async (updates: Partial<Settings>) => {
      const currentSettings = settings;
      if (!currentSettings) return;

      const newSettings: Settings = {
        ...toSettings(currentSettings),
        ...updates,
      };

      try {
        const response = await fetch("/api/admin/settings", {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(newSettings),
        });

        if (!response.ok) {
          throw new Error(
            await parseErrorDetail(response, t("toasts.settingsUpdateFailed"))
          );
        }

        navigation.refresh();
        await mutate(SWR_KEYS.settings);
      } catch (error) {
        toast.error(t("toasts.settingsUpdateFailed"));
      }
    },
    [settings, navigation, t]
  );

  return (
    <>
      <SettingsLayouts.Root>
        <SettingsLayouts.Header
          icon={route.icon}
          title={adminRouteTitle(route)}
          description={t("header.description")}
          divider
        />

        <SettingsLayouts.Body>
          {/* Chat */}
          <Card border="solid" rounding={4}>
            <Section alignItems="stretch">
              <InputHorizontal
                title={t("defaultLanguage.title")}
                description={t("defaultLanguage.description")}
                withLabel
                fillInput
              >
                <LanguageSelect
                  value={s.default_language}
                  onChange={(language) => {
                    void saveSettings({ default_language: language });
                  }}
                />
              </InputHorizontal>
              <ChatNamingModelSetting />
              <InputHorizontal
                title={t("multiModel.title")}
                description={t("multiModel.description")}
                withLabel
              >
                <InputSwitch
                  checked={s.multi_model_chat_enabled ?? true}
                  onCheckedChange={(checked) => {
                    void saveSettings({ multi_model_chat_enabled: checked });
                  }}
                />
              </InputHorizontal>
              <InputHorizontal
                title={t("deepResearch.title")}
                description={t("deepResearch.description")}
                withLabel
              >
                <InputSwitch
                  checked={s.deep_research_enabled ?? true}
                  onCheckedChange={(checked) => {
                    void saveSettings({ deep_research_enabled: checked });
                  }}
                />
              </InputHorizontal>
              <InputHorizontal
                title={t("autoScroll.title")}
                description={t("autoScroll.description")}
                withLabel
              >
                <InputSwitch
                  checked={s.auto_scroll ?? false}
                  onCheckedChange={(checked) => {
                    void saveSettings({ auto_scroll: checked });
                  }}
                />
              </InputHorizontal>
              {/* Below Business, or with no connectors, the row stays as is;
              only its switch is locked. */}
              <InputHorizontal
                title={t("searchMode.title")}
                tag={!businessTier ? plans[Tier.BUSINESS].tag : betaTag}
                description={t("searchMode.description")}
                withLabel
                disabled={!businessTier || uniqueSources.length === 0}
                disabledTooltip={
                  !businessTier
                    ? plans[Tier.BUSINESS].tooltip
                    : t("searchMode.noConnectorsTooltip")
                }
              >
                <InputSwitch
                  checked={businessTier ? (s.search_ui_enabled ?? true) : false}
                  onCheckedChange={(checked) => {
                    void saveSettings({ search_ui_enabled: checked });
                  }}
                />
              </InputHorizontal>
              <InputHorizontal
                title={t("autoDetectFilters.title")}
                description={t("autoDetectFilters.description")}
                withLabel
              >
                <InputSwitch
                  checked={s.auto_detect_search_filters ?? true}
                  onCheckedChange={(checked) => {
                    void saveSettings({ auto_detect_search_filters: checked });
                  }}
                />
              </InputHorizontal>
            </Section>
          </Card>

          {/* Search */}
          <Card border="solid" rounding={4}>
            <Section alignItems="stretch">
              <SearchDecisionModelSetting />
            </Section>
          </Card>

          <Divider paddingParallel={0} paddingPerpendicular={0} />

          {/* Team context */}
          <Section gap={4}>
            <InputVertical
              title={t("teamName.title")}
              subDescription={t("teamName.description")}
              withLabel
            >
              <InputTypeIn
                placeholder={t("teamName.placeholder")}
                value={companyName}
                onChange={(e) => setCompanyName(e.target.value)}
                onBlur={() => {
                  if (companyName !== savedCompanyName.current) {
                    void saveSettings({
                      company_name: companyName || null,
                    });
                    savedCompanyName.current = companyName;
                  }
                }}
              />
            </InputVertical>

            <InputVertical
              title={t("teamContext.title")}
              subDescription={t("teamContext.description")}
              withLabel
            >
              <InputTextArea
                placeholder={t("teamContext.placeholder", {
                  appName: settings.appName,
                })}
                rows={4}
                maxRows={10}
                autoResize
                value={companyDescription}
                onChange={(e) => setCompanyDescription(e.target.value)}
                onBlur={() => {
                  if (companyDescription !== savedCompanyDescription.current) {
                    void saveSettings({
                      company_description: companyDescription || null,
                    });
                    savedCompanyDescription.current = companyDescription;
                  }
                }}
              />
            </InputVertical>
          </Section>

          <InputHorizontal
            title={t("systemPrompt.title")}
            description={t("systemPrompt.description")}
          >
            <Button
              prominence="tertiary"
              icon={SvgAddLines}
              onClick={() => setSystemPromptModalOpen(true)}
            >
              {t("systemPrompt.modifyButton.label")}
            </Button>
          </InputHorizontal>

          <Divider paddingParallel={0} paddingPerpendicular={0} />

          <Disabled disabled={s.disable_default_assistant ?? false}>
            <div>
              <Section gap={6}>
                {/* Connectors */}
                <Section gap={3}>
                  <Section
                    flexDirection="row"
                    justifyContent="between"
                    alignItems="center"
                    gap={1}
                    wrap
                  >
                    <Section width="fit" alignItems="start">
                      <Content
                        font="main-content-emphasis"
                        title={t("connectors.title")}
                        description={t("connectors.description")}
                      />
                    </Section>
                    {uniqueSources.length > 0 && (
                      <Button
                        {...navigation.linkTo("/admin/indexing-status")}
                        prominence="tertiary"
                        rightIcon={SvgExternalLink}
                      >
                        {t("connectors.manageAllButton.label")}
                      </Button>
                    )}
                  </Section>

                  {uniqueSources.length === 0 ? (
                    <EmptyMessageCard
                      sizePreset="main-ui"
                      title={t("connectors.empty.title")}
                    />
                  ) : (
                    <Section
                      flexDirection="row"
                      justifyContent="start"
                      alignItems="center"
                      gap={1}
                      wrap
                    >
                      {uniqueSources.map((source) => {
                        const meta = getSourceMetadata(source);
                        return (
                          <div key={source} className="w-40">
                            <Card padding={2} border="solid">
                              <Content
                                font="main-ui-action"
                                icon={meta.icon}
                                title={meta.displayName}
                              />
                            </Card>
                          </div>
                        );
                      })}
                    </Section>
                  )}
                </Section>

                {/* Actions & Tools */}
                <Collapsible
                  title={t("tools.title")}
                  description={t("tools.description")}
                >
                  <Section gap={6} alignItems="stretch">
                    <Section gap={2} alignItems="stretch">
                      {vectorDbEnabled && searchTool && (
                        <Card border="solid" rounding={4}>
                          <InputHorizontal
                            title={t("tools.internalSearch.title")}
                            description={t("tools.internalSearch.description")}
                            withLabel
                          >
                            <InputSwitch
                              checked={isToolEnabled(searchTool.id)}
                              onCheckedChange={(checked) =>
                                void toggleTool(searchTool.id, checked)
                              }
                            />
                          </InputHorizontal>
                        </Card>
                      )}

                      <Card border="solid" rounding={4}>
                        <InputHorizontal
                          title={t("tools.imageGeneration.title")}
                          description={t("tools.imageGeneration.description")}
                          disabled={!imageGenTool}
                          disabledTooltip={t(
                            "tools.imageGeneration.disabledTooltip"
                          )}
                          withLabel
                        >
                          <InputSwitch
                            checked={
                              imageGenTool
                                ? isToolEnabled(imageGenTool.id)
                                : false
                            }
                            onCheckedChange={(checked) =>
                              imageGenTool &&
                              void toggleTool(imageGenTool.id, checked)
                            }
                          />
                        </InputHorizontal>
                      </Card>

                      <Card border="solid" rounding={4}>
                        <InputHorizontal
                          title={t("tools.webSearch.title")}
                          description={t("tools.webSearch.description")}
                          disabled={!webSearchTool}
                          withLabel
                        >
                          <InputSwitch
                            checked={
                              webSearchTool
                                ? isToolEnabled(webSearchTool.id)
                                : false
                            }
                            onCheckedChange={(checked) =>
                              webSearchTool &&
                              void toggleTool(webSearchTool.id, checked)
                            }
                          />
                        </InputHorizontal>
                      </Card>

                      <Card border="solid" rounding={4}>
                        <InputHorizontal
                          title={t("tools.openUrl.title")}
                          description={t("tools.openUrl.description")}
                          disabled={!openURLTool}
                          withLabel
                        >
                          <InputSwitch
                            checked={
                              openURLTool
                                ? isToolEnabled(openURLTool.id)
                                : false
                            }
                            onCheckedChange={(checked) =>
                              openURLTool &&
                              void toggleTool(openURLTool.id, checked)
                            }
                          />
                        </InputHorizontal>
                      </Card>

                      <Card border="solid" rounding={4}>
                        <InputHorizontal
                          title={t("tools.codeInterpreter.title")}
                          description={t("tools.codeInterpreter.description")}
                          disabled={!codeInterpreterTool}
                          withLabel
                        >
                          <InputSwitch
                            checked={
                              codeInterpreterTool
                                ? isToolEnabled(codeInterpreterTool.id)
                                : false
                            }
                            onCheckedChange={(checked) =>
                              codeInterpreterTool &&
                              void toggleTool(codeInterpreterTool.id, checked)
                            }
                          />
                        </InputHorizontal>
                      </Card>
                    </Section>

                    <MessageCard
                      variant="info"
                      title={markdown(
                        t("tools.pluginsNote", {
                          url: ADMIN_ROUTES.INTEGRATIONS.path,
                        })
                      )}
                    />
                  </Section>
                </Collapsible>
              </Section>
            </div>
          </Disabled>

          <Divider paddingParallel={0} paddingPerpendicular={0} />

          {/* Advanced Options */}
          <Collapsible defaultOpen={false} title={t("advanced.title")}>
            <Section gap={4}>
              <Card border="solid" rounding={4}>
                <InputVertical
                  title={t("fileLimits.title")}
                  description={t("fileLimits.description")}
                  withLabel
                >
                  <FileSizeLimitFields
                    saveSettings={saveSettings}
                    initialUploadSizeMb={
                      (s.user_file_max_upload_size_mb ?? 0) <= 0
                        ? (s.default_user_file_max_upload_size_mb?.toString() ??
                          "100")
                        : s.user_file_max_upload_size_mb!.toString()
                    }
                    defaultUploadSizeMb={
                      s.default_user_file_max_upload_size_mb?.toString() ??
                      "100"
                    }
                    initialTokenThresholdK={
                      s.file_token_count_threshold_k == null
                        ? (s.default_file_token_count_threshold_k?.toString() ??
                          "200")
                        : s.file_token_count_threshold_k === 0
                          ? ""
                          : s.file_token_count_threshold_k.toString()
                    }
                    defaultTokenThresholdK={
                      s.default_file_token_count_threshold_k?.toString() ??
                      "200"
                    }
                    maxAllowedUploadSizeMb={s.max_allowed_upload_size_mb}
                  />
                </InputVertical>
              </Card>

              <Card border="solid" rounding={4}>
                <Section>
                  <InputHorizontal
                    title={t("disableDefaultChat.title")}
                    description={markdown(t("disableDefaultChat.description"))}
                    withLabel
                  >
                    <InputSwitch
                      id="disable_default_assistant"
                      checked={s.disable_default_assistant ?? false}
                      onCheckedChange={(checked) => {
                        void saveSettings({
                          disable_default_assistant: checked,
                        });
                      }}
                    />
                  </InputHorizontal>
                </Section>
              </Card>
            </Section>
          </Collapsible>
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>

      <Modal
        open={systemPromptModalOpen}
        onOpenChange={setSystemPromptModalOpen}
      >
        <Modal.Content width="xl" height="fit">
          <Formik
            initialValues={{
              system_prompt:
                defaultAgentConfig?.system_prompt ??
                defaultAgentConfig?.default_system_prompt ??
                "",
            }}
            onSubmit={async ({ system_prompt }) => {
              try {
                const response = await fetch("/api/admin/default-assistant", {
                  method: "PATCH",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ system_prompt }),
                });
                if (!response.ok) {
                  throw new Error(
                    await parseErrorDetail(
                      response,
                      t("toasts.systemPromptUpdateFailed")
                    )
                  );
                }
                await mutateDefaultAgent();
                setSystemPromptModalOpen(false);
              } catch {
                toast.error(t("toasts.systemPromptUpdateFailed"));
              }
            }}
          >
            {({ dirty, isSubmitting, submitForm, setFieldValue }) => {
              const defaultPrompt =
                defaultAgentConfig?.default_system_prompt ?? "";

              const handleRestore = () => {
                void setFieldValue("system_prompt", defaultPrompt);
              };

              return (
                <Form>
                  <Modal.Header
                    icon={SvgAddLines}
                    title={t("systemPrompt.title")}
                    description={t("systemPrompt.modal.description")}
                    onClose={() => setSystemPromptModalOpen(false)}
                  />
                  <Modal.Body>
                    <Section gap={1} alignItems="start">
                      <Hoverable.Root group="systemPromptRestore" width="full">
                        <InputTextAreaField
                          name="system_prompt"
                          placeholder={t("systemPrompt.modal.placeholder")}
                          rows={8}
                          maxRows={20}
                          autoResize
                          rightSection={
                            <Hoverable.Item
                              group="systemPromptRestore"
                              variant="appear-on-hover"
                            >
                              <Button
                                icon={SvgRefreshCw}
                                tooltip={t("systemPrompt.modal.restoreTooltip")}
                                prominence="internal"
                                onClick={handleRestore}
                              />
                            </Hoverable.Item>
                          }
                        />
                      </Hoverable.Root>
                      <Text font="secondary-body" color="text-03">
                        {markdown(
                          t("systemPrompt.modal.placeholders.intro"),
                          // The placeholder names are literal template tokens,
                          // not copy, so they are passed as ICU arguments to
                          // keep them out of the translated string.
                          t("systemPrompt.modal.placeholders.currentDatetime", {
                            token: "{{CURRENT_DATETIME}}",
                          }),
                          t(
                            "systemPrompt.modal.placeholders.citationGuidance",
                            { token: "{{CITATION_GUIDANCE}}" }
                          ),
                          t("systemPrompt.modal.placeholders.citationNote"),
                          t("systemPrompt.modal.placeholders.reminderTag", {
                            token: "{{REMINDER_TAG_DESCRIPTION}}",
                          })
                        )}
                      </Text>
                    </Section>
                    <MessageCard
                      innerPadding={1}
                      title={t("systemPrompt.modal.caution.title")}
                      description={t("systemPrompt.modal.caution.description")}
                      outerPadding={1}
                    />
                  </Modal.Body>
                  <Modal.Footer>
                    <Button
                      prominence="secondary"
                      onClick={() => setSystemPromptModalOpen(false)}
                    >
                      {t("systemPrompt.modal.cancelButton.label")}
                    </Button>
                    <Button
                      prominence="primary"
                      onClick={submitForm}
                      disabled={!dirty || isSubmitting}
                    >
                      {t("systemPrompt.modal.saveButton.label")}
                    </Button>
                  </Modal.Footer>
                </Form>
              );
            }}
          </Formik>
        </Modal.Content>
      </Modal>
    </>
  );
}
