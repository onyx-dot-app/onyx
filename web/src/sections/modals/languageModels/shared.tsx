"use client";

import React, { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Formik, Form, useFormikContext } from "formik";
import type { FormikConfig } from "formik";
import { cn } from "@opal/utils";
import { markdown } from "@opal/utils";
import { Hoverable, Interactive } from "@opal/core";
import { useTierAtLeast } from "@/hooks/useTierAtLeast";
import { Tier } from "@/lib/settings/types";
import { useAgents } from "@/lib/agents/hooks";
import { useUserGroups } from "@/lib/hooks";
import type {
  LLMProviderView,
  ModelConfiguration,
} from "@/lib/languageModels/types";
import { Checkbox } from "@opal/components";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import { InputTypeIn } from "@opal/components";
import InputComboBox from "@/refresh-components/inputs/InputComboBox";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import PasswordInputTypeInField from "@/refresh-components/form/PasswordInputTypeInField";
import { Switch } from "@opal/components";
import Text from "@/refresh-components/texts/Text";
import { Button } from "@opal/components";
import { BaseLLMFormValues } from "@/sections/modals/languageModels/utils";
import type { RichStr } from "@opal/types";
import { Section } from "@/layouts/general-layouts";
import {
  Content,
  InputDivider,
  InputHorizontal,
  InputPadder,
  InputVertical,
  Section as OpalSection,
  toast,
} from "@opal/layouts";
import {
  ModelSettingsPopover,
  type ModelSettingsPatch,
} from "@/sections/modals/languageModels/ModelSettingsPopover";
import { setDefaultLlmModelAndRefresh } from "@/lib/languageModels/cache";
import { modelDisplayName } from "@/lib/languageModels/utils";
import { useAdminLLMProviders } from "@/lib/languageModels/hooks";
import { useSWRConfig } from "swr";
import {
  SvgArrowExchange,
  SvgChevronDown,
  SvgOnyxOctagon,
  SvgOrganization,
  SvgPlusCircle,
  SvgRefreshCw,
  SvgSparkle,
  SvgUserManage,
  SvgUsers,
  SvgX,
  SvgSimpleLoader,
} from "@opal/icons";
import SvgOnyxLogo from "@opal/logos/onyx-logo";
import { Card, EmptyMessageCard } from "@opal/components";
import { ContentAction } from "@opal/layouts";
import type { ContentMdEditHandle } from "@opal/layouts/content/ContentMd";
import { SvgEdit } from "@opal/icons";
import AgentAvatar from "@/refresh-components/avatars/AgentAvatar";
import useUsers from "@/hooks/useUsers";
import { Modal } from "@opal/components";
import { getProvider } from "@/lib/languageModels";
import { useSettings } from "@/lib/settings/hooks";

// ─── DisplayNameField ────────────────────────────────────────────────────────

export interface DisplayNameFieldProps {
  disabled?: boolean;
}

export function DisplayNameField({ disabled }: DisplayNameFieldProps = {}) {
  const t = useTranslations("admin.languageModels.modals");
  return (
    <InputPadder>
      <InputVertical
        withLabel="name"
        title={t("setup.displayNameField.title")}
        suffix={t("setup.optionalSuffix.label")}
        subDescription={t("setup.displayNameField.description")}
      >
        <InputTypeInField
          name="name"
          placeholder={t("setup.displayNameField.placeholder")}
          variant={disabled ? "disabled" : undefined}
        />
      </InputVertical>
    </InputPadder>
  );
}

// ─── APIKeyField ─────────────────────────────────────────────────────────────

export interface APIKeyFieldProps {
  /** Formik field name. @default "api_key" */
  name?: string;
  optional?: boolean;
  providerName?: string;
  subDescription?: string | RichStr;
}
export function APIKeyField({
  name = "api_key",
  optional = false,
  providerName,
  subDescription,
}: APIKeyFieldProps) {
  const t = useTranslations("admin.languageModels.modals");
  return (
    <InputPadder>
      <InputVertical
        withLabel={name}
        title={t("setup.apiKeyField.title")}
        subDescription={
          subDescription
            ? subDescription
            : providerName
              ? t("setup.apiKeyField.providerDescription", {
                  provider: providerName,
                })
              : t("setup.apiKeyField.description")
        }
        suffix={optional ? t("setup.optionalSuffix.label") : undefined}
      >
        <PasswordInputTypeInField name={name} />
      </InputVertical>
    </InputPadder>
  );
}

// ─── APIBaseField ───────────────────────────────────────────────────────────

/**
 * Builds the API Base URL `subDescription` for self-hosted and custom
 * providers. These point at a service on the admin's own machine, which
 * `localhost` does not reach from inside a container — so when Onyx is
 * containerized, a note about `host.docker.internal` goes between
 * `description` and `suffix`.
 */
export function useApiBaseSubDescription(
  description?: string,
  suffix?: string
): RichStr | undefined {
  const t = useTranslations("admin.languageModels.modals");
  const settings = useSettings();
  const sentences = [
    description,
    settings.is_containerized
      ? t("setup.apiBaseField.containerizedNote")
      : undefined,
    suffix,
  ].filter((sentence) => sentence !== undefined);
  return sentences.length > 0 ? markdown(sentences.join(" ")) : undefined;
}

export interface APIBaseFieldProps {
  optional?: boolean;
  subDescription?: string | RichStr;
  placeholder?: string;
  /** Rendered inside the input on the right (e.g. a restore-default control). */
  rightChildren?: React.ReactNode;
}
export function APIBaseField({
  optional = false,
  subDescription,
  placeholder = "https://",
  rightChildren,
}: APIBaseFieldProps) {
  const t = useTranslations("admin.languageModels.modals");
  return (
    <InputPadder>
      <InputVertical
        withLabel="api_base"
        title={t("setup.apiBaseField.title")}
        subDescription={subDescription}
        suffix={optional ? t("setup.optionalSuffix.label") : undefined}
      >
        <InputTypeInField
          name="api_base"
          placeholder={placeholder}
          rightChildren={rightChildren}
        />
      </InputVertical>
    </InputPadder>
  );
}

// ─── ModelsAccessField ──────────────────────────────────────────────────────

/** Prefix used to distinguish group IDs from agent IDs in the combobox. */
const GROUP_PREFIX = "group:";
const AGENT_PREFIX = "agent:";

export function ModelAccessField() {
  const t = useTranslations("admin.languageModels.modals");
  const formikProps = useFormikContext<BaseLLMFormValues>();
  const { agents } = useAgents();
  const { data: userGroups, isLoading: userGroupsIsLoading } = useUserGroups();
  const { data: usersData } = useUsers({ includeApiKeys: false });
  const businessTier = useTierAtLeast(Tier.BUSINESS);

  const adminCount = usersData?.accepted.filter((u) => u.is_admin).length ?? 0;

  const isPublic = formikProps.values.is_public;
  const selectedGroupIds = formikProps.values.groups ?? [];
  const selectedAgentIds = formikProps.values.personas ?? [];

  // Build a flat list of combobox options from groups + agents
  const groupOptions =
    businessTier && !userGroupsIsLoading && userGroups
      ? userGroups.map((g) => ({
          value: `${GROUP_PREFIX}${g.id}`,
          label: g.name,
          description: t("access.groupOption.description"),
        }))
      : [];

  const agentOptions = agents.map((a) => ({
    value: `${AGENT_PREFIX}${a.id}`,
    label: a.name,
    description: t("access.agentOption.description"),
  }));

  // Exclude already-selected items from the dropdown
  const selectedKeys = new Set([
    ...selectedGroupIds.map((id) => `${GROUP_PREFIX}${id}`),
    ...selectedAgentIds.map((id) => `${AGENT_PREFIX}${id}`),
  ]);

  const availableOptions = [...groupOptions, ...agentOptions].filter(
    (opt) => !selectedKeys.has(opt.value)
  );

  // Resolve selected IDs back to full objects for display
  const groupById = new Map((userGroups ?? []).map((g) => [g.id, g]));
  const agentMap = new Map(agents.map((a) => [a.id, a]));

  function handleAccessChange(value: string) {
    if (value === "public") {
      formikProps.setFieldValue("is_public", true);
      formikProps.setFieldValue("groups", []);
      formikProps.setFieldValue("personas", []);
    } else {
      formikProps.setFieldValue("is_public", false);
    }
  }

  function handleSelect(compositeValue: string) {
    if (compositeValue.startsWith(GROUP_PREFIX)) {
      const id = Number(compositeValue.slice(GROUP_PREFIX.length));
      if (!selectedGroupIds.includes(id)) {
        formikProps.setFieldValue("groups", [...selectedGroupIds, id]);
      }
    } else if (compositeValue.startsWith(AGENT_PREFIX)) {
      const id = Number(compositeValue.slice(AGENT_PREFIX.length));
      if (!selectedAgentIds.includes(id)) {
        formikProps.setFieldValue("personas", [...selectedAgentIds, id]);
      }
    }
  }

  function handleRemoveGroup(id: number) {
    formikProps.setFieldValue(
      "groups",
      selectedGroupIds.filter((gid) => gid !== id)
    );
  }

  function handleRemoveAgent(id: number) {
    formikProps.setFieldValue(
      "personas",
      selectedAgentIds.filter((aid) => aid !== id)
    );
  }

  return (
    <div className="flex flex-col w-full">
      <InputPadder>
        <InputHorizontal
          withLabel="is_public"
          title={t("access.field.title")}
          description={t("access.field.description")}
        >
          <InputSelect
            value={isPublic ? "public" : "private"}
            onValueChange={handleAccessChange}
          >
            <InputSelect.Trigger placeholder={t("access.select.placeholder")} />
            <InputSelect.Content>
              <InputSelect.Item value="public" icon={SvgOrganization}>
                {t("access.public.label")}
              </InputSelect.Item>
              <InputSelect.Item value="private" icon={SvgUsers}>
                {t("access.private.label")}
              </InputSelect.Item>
            </InputSelect.Content>
          </InputSelect>
        </InputHorizontal>
      </InputPadder>

      {!isPublic && (
        <Card background="light" border="none" padding={2}>
          <Section gap={2}>
            <InputComboBox
              placeholder={t("access.comboBox.placeholder")}
              value=""
              onChange={() => {}}
              onValueChange={handleSelect}
              options={availableOptions}
              strict
              searchIcon
            />

            <Card background="heavy" border="none" padding={2}>
              <ContentAction
                icon={SvgUserManage}
                title={t("access.admin.title")}
                description={t("access.memberCount.label", {
                  count: adminCount,
                })}
                sizePreset="main-ui"
                variant="section"
                rightChildren={
                  <Text secondaryBody text03>
                    {t("access.admin.sharedNote")}
                  </Text>
                }
                padding={0}
              />
            </Card>
            {selectedGroupIds.length > 0 && (
              <div className="grid grid-cols-2 gap-1 w-full">
                {selectedGroupIds.map((id) => {
                  const group = groupById.get(id);
                  const memberCount = group?.users.length ?? 0;
                  return (
                    <div key={`group-${id}`} className="min-w-0">
                      <Card background="heavy" border="none" padding={2}>
                        <ContentAction
                          icon={SvgUsers}
                          title={group?.name ?? t("access.group.name", { id })}
                          description={t("access.memberCount.label", {
                            count: memberCount,
                          })}
                          sizePreset="main-ui"
                          variant="section"
                          rightChildren={
                            <Button
                              size="sm"
                              prominence="internal"
                              icon={SvgX}
                              onClick={() => handleRemoveGroup(id)}
                              type="button"
                            />
                          }
                          padding={0}
                        />
                      </Card>
                    </div>
                  );
                })}
              </div>
            )}

            <InputDivider />

            {selectedAgentIds.length > 0 ? (
              <div className="grid grid-cols-2 gap-1 w-full">
                {selectedAgentIds.map((id) => {
                  const agent = agentMap.get(id);
                  return (
                    <div key={`agent-${id}`} className="min-w-0">
                      <Card background="heavy" border="none" padding={2}>
                        <ContentAction
                          icon={
                            agent
                              ? () => <AgentAvatar agent={agent} size={20} />
                              : SvgSparkle
                          }
                          title={agent?.name ?? t("access.agent.name", { id })}
                          description={t("access.agentOption.description")}
                          sizePreset="main-ui"
                          variant="section"
                          rightChildren={
                            <Button
                              size="sm"
                              prominence="internal"
                              icon={SvgX}
                              onClick={() => handleRemoveAgent(id)}
                              type="button"
                            />
                          }
                          padding={0}
                        />
                      </Card>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="w-full p-2">
                <Content
                  icon={SvgOnyxOctagon}
                  title={t("access.noAgents.title")}
                  description={t("access.noAgents.description")}
                  variant="section"
                  sizePreset="main-ui"
                />
              </div>
            )}
          </Section>
        </Card>
      )}
    </div>
  );
}

// ─── RefetchButton ──────────────────────────────────────────────────

/**
 * Manages an AbortController so that clicking the button cancels any
 * in-flight fetch before starting a new one. Also aborts on unmount.
 */
interface RefetchButtonProps {
  onRefetch: (signal: AbortSignal) => Promise<void> | void;
}
function RefetchButton({ onRefetch }: RefetchButtonProps) {
  const t = useTranslations("admin.languageModels.modals");
  const abortRef = useRef<AbortController | null>(null);
  const [isFetching, setIsFetching] = useState(false);

  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  return (
    <Button
      prominence="tertiary"
      icon={isFetching ? SvgSimpleLoader : SvgRefreshCw}
      onClick={async () => {
        abortRef.current?.abort();
        const controller = new AbortController();
        abortRef.current = controller;
        setIsFetching(true);
        try {
          await onRefetch(controller.signal);
        } catch (err) {
          if (err instanceof DOMException && err.name === "AbortError") return;
          toast.error(
            err instanceof Error ? err.message : t("models.refetch.errorToast")
          );
        } finally {
          if (!controller.signal.aborted) {
            setIsFetching(false);
          }
        }
      }}
      disabled={isFetching}
    />
  );
}

// ─── ModelsField ─────────────────────────────────────────────────────

const FOLD_THRESHOLD = 3;

// ─── Model metadata helpers (Nebius TokenFactory picker) ────────────────────

function formatContextSize(tokens: number | null | undefined): string {
  if (!tokens || tokens <= 0) return "";
  if (tokens >= 1_000_000) {
    const m = tokens / 1_000_000;
    return `${Number.isInteger(m) ? m : m.toFixed(1)}M`;
  }
  if (tokens >= 1000) return `${Math.round(tokens / 1000)}K`;
  return String(tokens);
}

// Common non-ISO-3166 codes the provider may report → the ISO alpha-2 code
// whose regional-indicator sequence actually has a flag glyph.
const COUNTRY_CODE_ALIASES: Record<string, string> = {
  UK: "GB", // United Kingdom is "GB" in ISO 3166-1; "UK" has no flag glyph
};

function countryCodeToFlag(code: string | null | undefined): string {
  if (!code || code.length !== 2) return "";
  const upper = code.toUpperCase();
  const normalized = COUNTRY_CODE_ALIASES[upper] ?? upper;
  const first = 0x1f1e6 + normalized.charCodeAt(0) - 65;
  const second = 0x1f1e6 + normalized.charCodeAt(1) - 65;
  return String.fromCodePoint(first, second);
}

/** Models that ship extra picker metadata (e.g. Nebius TokenFactory); most
 *  providers don't, in which case the row renders without a metadata line. */
function hasModelMetadata(model: ModelConfiguration): boolean {
  return (
    model.quantization != null ||
    model.country_code != null ||
    (model.supported_features?.length ?? 0) > 0
  );
}

/** Compact "128K · 🇫🇮 · fp8 · tools, reasoning" metadata line. */
function buildModelDescription(model: ModelConfiguration): string | undefined {
  if (!hasModelMetadata(model)) return undefined;
  const parts: string[] = [];
  const context = formatContextSize(model.max_input_tokens);
  if (context) parts.push(context);
  const flag = countryCodeToFlag(model.country_code);
  if (flag) parts.push(flag);
  if (model.quantization) parts.push(model.quantization);
  if (model.supported_features?.length) {
    parts.push(model.supported_features.join(", "));
  }
  return parts.length > 0 ? parts.join("  ·  ") : undefined;
}

/** Eye marker for vision models, shown on the right of the picker row. */
function modelRightChildren(
  model: ModelConfiguration,
  visionTitle: string
): React.ReactNode {
  if (!hasModelMetadata(model) || !model.supports_image_input) return undefined;
  return (
    <Text secondaryBody text03 title={visionTitle}>
      👁
    </Text>
  );
}

interface ModelRowProps {
  model: ModelConfiguration;
  isAutoMode: boolean;
  isDefaultModel: boolean;
  onToggleVisibility: (visible: boolean) => void;
  onRename: (value: string | undefined) => void;
  onSettingsChange: (patch: ModelSettingsPatch) => void;
  onSetDefaultModel?: () => void;
}

/**
 * A single selectable model row.
 *
 * The row is a clickable `<div role="button">` rather than a real `<button>`,
 * because it hosts real action buttons (rename, settings, set as default) and
 * a `<button>` inside a `<button>` is invalid HTML that triggers a React
 * hydration error.
 *
 * This mirrors `LineItemButton`'s internals (Stateful → Container →
 * ContentAction) but with a typeless `Interactive.Container`, which renders a
 * `<div>` instead of a `<button>`.
 */
function ModelRow({
  model,
  isAutoMode,
  isDefaultModel,
  onToggleVisibility,
  onRename,
  onSettingsChange,
  onSetDefaultModel,
}: ModelRowProps) {
  const t = useTranslations("admin.languageModels.modals");
  const editHandle = useRef<ContentMdEditHandle>(null);
  // Keeps the hover-revealed actions visible while the settings popover,
  // which is portaled outside the row, is open.
  const [settingsOpen, setSettingsOpen] = useState(false);
  const displayName = modelDisplayName(model);
  // In auto mode every model is shown, so the row is always "selected" and the
  // visibility toggle is disabled.
  const isSelected = isAutoMode || model.is_visible;
  const toggleVisibility = isAutoMode
    ? undefined
    : () => onToggleVisibility(!model.is_visible);
  // A click that blurs and commits an inline rename reaches the row after the
  // edit input unmounts, so the input's presence is sampled at pointerdown.
  const renamingAtPointerDown = useRef(false);
  // The row is clickable, but it also hosts real buttons (rename, settings).
  // Their clicks, including ones the browser synthesizes from Enter, must not
  // toggle the model.
  const toggleFromRow = toggleVisibility
    ? (e: React.MouseEvent) => {
        if (renamingAtPointerDown.current) return;
        const interactive = (e.target as HTMLElement).closest(
          'button, input, textarea, [contenteditable="true"]'
        );
        if (interactive) return;
        toggleVisibility();
      }
    : undefined;

  return (
    <Hoverable.Root
      group="model-row"
      interaction={settingsOpen ? "hover" : "rest"}
      data-model-name={model.name}
    >
      <Interactive.Stateful
        variant="select-heavy"
        state={isSelected ? "selected" : "empty"}
        onPointerDownCapture={(e: React.PointerEvent) => {
          // Scoped to the title row: the checkbox also owns a hidden input.
          renamingAtPointerDown.current =
            e.currentTarget.querySelector(".opal-content-md-title-row input") !=
            null;
        }}
        onClick={toggleFromRow}
        role={toggleVisibility ? "button" : undefined}
        tabIndex={toggleVisibility ? 0 : undefined}
        onKeyDown={
          toggleVisibility
            ? (e: React.KeyboardEvent) => {
                // Only the row itself. React bubbles events from portaled
                // children too, so a key inside the settings popover would
                // otherwise toggle the model.
                if (e.target !== e.currentTarget) return;
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  toggleVisibility();
                }
              }
            : undefined
        }
      >
        <Interactive.Container width="full" size="fit" rounding={3}>
          <div className="w-full p-1.5">
            <ContentAction
              color="interactive"
              variant="section"
              sizePreset="main-ui"
              center
              icon={() => <Checkbox checked={isSelected} />}
              title={displayName}
              description={buildModelDescription(model)}
              rightChildren={
                <OpalSection
                  flexDirection="row"
                  width="fit"
                  height="auto"
                  gap={1}
                >
                  {modelRightChildren(
                    model,
                    t("models.row.visionMarker.title")
                  )}
                  <Hoverable.Item group="model-row" variant="appear-on-hover">
                    <OpalSection
                      flexDirection="row"
                      width="fit"
                      height="auto"
                      gap={1}
                    >
                      <Button
                        icon={SvgEdit}
                        prominence="internal"
                        size="sm"
                        tooltip={t("models.row.renameButton.tooltip")}
                        onClick={(e: React.MouseEvent) => {
                          e.stopPropagation();
                          editHandle.current?.startEditing();
                        }}
                      />
                      <ModelSettingsPopover
                        model={model}
                        onChange={onSettingsChange}
                        onOpenChange={setSettingsOpen}
                      />
                      {!isDefaultModel && onSetDefaultModel && (
                        <Button
                          prominence="internal"
                          size="sm"
                          onClick={(e: React.MouseEvent) => {
                            e.stopPropagation();
                            onSetDefaultModel();
                          }}
                        >
                          {t("models.row.setDefaultButton.label")}
                        </Button>
                      )}
                    </OpalSection>
                  </Hoverable.Item>
                  {isDefaultModel && (
                    <Text
                      secondaryAction
                      nowrap
                      className="px-1.5 py-1 text-action-selection-05"
                    >
                      {t("models.row.defaultLabel")}
                    </Text>
                  )}
                </OpalSection>
              }
              editable
              editHandle={editHandle}
              onTitleChange={(newTitle) => onRename(newTitle || undefined)}
              padding={0}
            />
          </div>
        </Interactive.Container>
      </Interactive.Stateful>
    </Hoverable.Root>
  );
}

export interface ModelSelectionFieldProps {
  shouldShowAutoUpdateToggle: boolean;
  onRefetch?: (signal: AbortSignal) => Promise<void> | void;
  /** Called when the user adds a custom model by name. Enables the "Add Model" input. */
  onAddModel?: (modelName: string) => void;
  /** Overrides the empty-state copy shown when no models are loaded. */
  emptyMessage?: string;
}
export function ModelSelectionField({
  shouldShowAutoUpdateToggle,
  onRefetch,
  onAddModel,
  emptyMessage,
}: ModelSelectionFieldProps) {
  const t = useTranslations("admin.languageModels.modals");
  const formikProps = useFormikContext<BaseLLMFormValues>();
  const { mutate } = useSWRConfig();
  const { defaultText } = useAdminLLMProviders();
  const providerId = formikProps.values.id;
  const [newModelName, setNewModelName] = useState("");
  const [isExpanded, setIsExpanded] = useState(false);
  // When the auto-update toggle is hidden, auto mode should have no effect —
  // otherwise models can't be deselected and "Select All" stays disabled.
  const isAutoMode =
    shouldShowAutoUpdateToggle && formikProps.values.is_auto_mode;
  const models = formikProps.values.model_configurations;

  // Snapshot the original model visibility so we can restore it when
  // toggling auto mode back on.
  const originalModelsRef = useRef(models);
  useEffect(() => {
    if (originalModelsRef.current.length === 0 && models.length > 0) {
      originalModelsRef.current = models;
    }
  }, [models]);

  // Automatically derive test_model_name from model_configurations.
  // Any change to visibility or the model list syncs this automatically.
  useEffect(() => {
    const firstVisible = models.find((m) => m.is_visible)?.name;
    if (firstVisible !== formikProps.values.test_model_name) {
      formikProps.setFieldValue("test_model_name", firstVisible);
    }
  }, [models]); // eslint-disable-line react-hooks/exhaustive-deps

  function setVisibility(modelName: string, visible: boolean) {
    const updated = models.map((m) =>
      m.name === modelName ? { ...m, is_visible: visible } : m
    );
    formikProps.setFieldValue("model_configurations", updated);
  }

  function setModelSettings(modelName: string, patch: ModelSettingsPatch) {
    const updated = models.map((m) =>
      m.name === modelName ? { ...m, ...patch } : m
    );
    formikProps.setFieldValue("model_configurations", updated);
  }

  async function setDefaultModel(modelName: string) {
    if (providerId == null) return;
    await setDefaultLlmModelAndRefresh(providerId, modelName, mutate);
  }

  function setCustomDisplayName(modelName: string, value: string | undefined) {
    const updated = models.map((m) =>
      m.name === modelName
        ? { ...m, custom_display_name: value || undefined }
        : m
    );
    formikProps.setFieldValue("model_configurations", updated);
  }

  function handleToggleAutoMode(nextIsAutoMode: boolean) {
    formikProps.setFieldValue("is_auto_mode", nextIsAutoMode);
    if (nextIsAutoMode) {
      // Auto mode restores only the snapshot's visibility. Unsaved edits and
      // models discovered after mount survive the toggle.
      const originalByName = new Map(
        originalModelsRef.current.map((m) => [m.name, m])
      );
      formikProps.setFieldValue(
        "model_configurations",
        models.map((current) => {
          const original = originalByName.get(current.name);
          return original
            ? { ...current, is_visible: original.is_visible }
            : current;
        })
      );
    }
  }

  const allSelected = models.length > 0 && models.every((m) => m.is_visible);

  function handleToggleSelectAll() {
    const nextVisible = !allSelected;
    const updated = models.map((m) => ({
      ...m,
      is_visible: nextVisible,
    }));
    formikProps.setFieldValue("model_configurations", updated);
  }

  const visibleModels = models.filter((m) => m.is_visible);

  return (
    <Card background="light" border="none" padding={2}>
      <Section gap={2}>
        <InputHorizontal
          title={t("models.field.title")}
          description={t("models.field.description")}
          center
        >
          <Section flexDirection="row" gap={0}>
            <Button
              disabled={isAutoMode || models.length === 0}
              prominence="tertiary"
              size="md"
              onClick={handleToggleSelectAll}
            >
              {allSelected
                ? t("models.deselectAllButton.label")
                : t("models.selectAllButton.label")}
            </Button>
            {onRefetch && <RefetchButton onRefetch={onRefetch} />}
          </Section>
        </InputHorizontal>

        {models.length === 0 ? (
          <EmptyMessageCard
            title={emptyMessage ?? t("models.empty.title")}
            padding={2}
          />
        ) : (
          <Section gap={1} alignItems="stretch">
            {(() => {
              const baseModels = isAutoMode ? visibleModels : models;
              // Sort alphabetically by id for providers that ship rich model
              // metadata (Nebius TokenFactory) so the order is stable across
              // refetches; otherwise keep the given order.
              const displayModels = baseModels.some((m) => hasModelMetadata(m))
                ? [...baseModels].sort((a, b) => a.name.localeCompare(b.name))
                : baseModels;
              const isFoldable = displayModels.length > FOLD_THRESHOLD;
              const shownModels =
                isFoldable && !isExpanded
                  ? displayModels.slice(0, FOLD_THRESHOLD)
                  : displayModels;
              const defaultModelName =
                providerId != null && defaultText?.provider_id === providerId
                  ? defaultText.model_name
                  : undefined;

              return (
                <>
                  {shownModels.map((model) => (
                    <ModelRow
                      key={model.name}
                      model={model}
                      isAutoMode={isAutoMode}
                      onToggleVisibility={(visible) =>
                        setVisibility(model.name, visible)
                      }
                      onRename={(value) =>
                        setCustomDisplayName(model.name, value)
                      }
                      onSettingsChange={(patch) =>
                        setModelSettings(model.name, patch)
                      }
                      isDefaultModel={model.name === defaultModelName}
                      onSetDefaultModel={
                        providerId != null && model.is_visible
                          ? () => void setDefaultModel(model.name)
                          : undefined
                      }
                    />
                  ))}
                  {isFoldable && (
                    <Interactive.Stateless
                      prominence="tertiary"
                      onClick={() => setIsExpanded(!isExpanded)}
                    >
                      <Interactive.Container type="button" width="full">
                        <Content
                          sizePreset="secondary"
                          variant="body"
                          title={
                            isExpanded
                              ? t("models.foldButton.label")
                              : t("models.moreButton.label")
                          }
                          icon={() => (
                            <SvgChevronDown
                              className={cn(
                                "transition-transform",
                                isExpanded && "-rotate-180"
                              )}
                              size={14}
                            />
                          )}
                        />
                      </Interactive.Container>
                    </Interactive.Stateless>
                  )}
                </>
              );
            })()}
          </Section>
        )}

        {onAddModel && !isAutoMode && (
          <Section flexDirection="row" gap={2}>
            <div className="flex-1">
              <InputTypeIn
                placeholder={t("models.addModelInput.placeholder")}
                value={newModelName}
                onChange={(e) => setNewModelName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && newModelName.trim()) {
                    e.preventDefault();
                    const trimmed = newModelName.trim();
                    if (!models.some((m) => m.name === trimmed)) {
                      onAddModel(trimmed);
                      setNewModelName("");
                    }
                  }
                }}
              />
            </div>
            <Button
              prominence="secondary"
              icon={SvgPlusCircle}
              type="button"
              disabled={
                !newModelName.trim() ||
                models.some((m) => m.name === newModelName.trim())
              }
              onClick={() => {
                const trimmed = newModelName.trim();
                if (trimmed && !models.some((m) => m.name === trimmed)) {
                  onAddModel(trimmed);
                  setNewModelName("");
                }
              }}
            >
              {t("models.addModelButton.label")}
            </Button>
          </Section>
        )}

        {shouldShowAutoUpdateToggle && (
          <InputHorizontal
            title={t("models.autoUpdate.title")}
            description={t("models.autoUpdate.description")}
            withLabel
          >
            <Switch
              checked={isAutoMode}
              onCheckedChange={handleToggleAutoMode}
            />
          </InputHorizontal>
        )}
      </Section>
    </Card>
  );
}

// ─── ModalWrapper ─────────────────────────────────────────────────────

export interface ModalWrapperProps<
  T extends BaseLLMFormValues = BaseLLMFormValues,
> {
  providerName: string;
  llmProvider?: LLMProviderView;
  onClose: () => void;
  initialValues: T;
  validationSchema: FormikConfig<T>["validationSchema"];
  onSubmit: FormikConfig<T>["onSubmit"];
  children: React.ReactNode;
  description?: string;
}
export function ModalWrapper<T extends BaseLLMFormValues = BaseLLMFormValues>({
  providerName,
  llmProvider,
  onClose,
  initialValues,
  validationSchema,
  onSubmit,
  children,
  description,
}: ModalWrapperProps<T>) {
  return (
    <Formik
      initialValues={initialValues}
      validationSchema={validationSchema}
      validateOnMount
      onSubmit={onSubmit}
    >
      {() => (
        <ModalWrapperInner
          providerName={providerName}
          llmProvider={llmProvider}
          onClose={onClose}
          modelConfigurations={initialValues.model_configurations}
          description={description}
        >
          {children}
        </ModalWrapperInner>
      )}
    </Formik>
  );
}

interface ModalWrapperInnerProps {
  providerName: string;
  llmProvider?: LLMProviderView;
  onClose: () => void;
  modelConfigurations?: ModelConfiguration[];
  children: React.ReactNode;
  description?: string;
}
function ModalWrapperInner({
  providerName,
  llmProvider,
  onClose,
  modelConfigurations,
  children,
  description: descriptionOverride,
}: ModalWrapperInnerProps) {
  const t = useTranslations("admin.languageModels.modals");
  const { isValid, dirty, isSubmitting, status, setFieldValue, values } =
    useFormikContext<BaseLLMFormValues>();

  // When SWR resolves after mount, populate model_configurations if still
  // empty. test_model_name is then derived automatically by
  // ModelSelectionField's useEffect.
  useEffect(() => {
    if (
      modelConfigurations &&
      modelConfigurations.length > 0 &&
      values.model_configurations.length === 0
    ) {
      setFieldValue("model_configurations", modelConfigurations);
    }
  }, [modelConfigurations]); // eslint-disable-line react-hooks/exhaustive-deps

  const isTesting = status?.isTesting === true;
  const busy = isTesting || isSubmitting;

  const disabledTooltip = busy
    ? undefined
    : !isValid
      ? t("setup.submitButton.invalidTooltip")
      : !dirty
        ? t("setup.submitButton.pristineTooltip")
        : undefined;

  const {
    icon: providerIcon,
    companyName: providerDisplayName,
    productName: providerProductName,
  } = getProvider(providerName);

  const title = llmProvider
    ? markdown(
        t("setup.title.configure", {
          provider: llmProvider.name ?? providerProductName,
        })
      )
    : t("setup.title.create", { product: providerProductName });
  const description =
    descriptionOverride ??
    t("setup.description", {
      company: providerDisplayName,
      product: providerProductName,
    });

  return (
    <Modal open onOpenChange={onClose}>
      <Modal.Content width="lg" height="lg">
        <Form className="flex flex-col h-full min-h-0">
          <Modal.Header
            icon={providerIcon}
            moreIcon1={SvgArrowExchange}
            moreIcon2={SvgOnyxLogo}
            title={title}
            description={description}
            onClose={onClose}
          />
          <Modal.Body padding={2} gap={0}>
            {children}
          </Modal.Body>
          <Modal.Footer>
            <Button prominence="secondary" onClick={onClose} type="button">
              {t("setup.cancelButton.label")}
            </Button>
            <Button
              disabled={!isValid || !dirty || busy}
              type="submit"
              icon={busy ? SvgSimpleLoader : undefined}
              tooltip={disabledTooltip}
            >
              {llmProvider
                ? t("setup.updateButton.label")
                : t("setup.connectButton.label")}
            </Button>
          </Modal.Footer>
        </Form>
      </Modal.Content>
    </Modal>
  );
}
