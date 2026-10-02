"use client";

import { IconLoader } from "@opal/loaders";
import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useTranslations } from "next-intl";
import { Formik, Form, useFormikContext } from "formik";
import type { FormikConfig } from "formik";
import isEqual from "lodash/isEqual";
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
import { InputCheckbox } from "@opal/components";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import { InputTypeIn } from "@opal/components";
import { InputSingleComboBox } from "@opal/components";
import { InputSingleSelect } from "@opal/components";
import PasswordInputTypeInField from "@/refresh-components/form/PasswordInputTypeInField";
import { InputSwitch } from "@opal/components";
import Text from "@/refresh-components/texts/Text";
import { Button } from "@opal/components";
// The file's unqualified `Text` is the legacy component, kept for its
// existing call sites.
import { Text as OpalText } from "@opal/components";
import {
  BaseLLMFormValues,
  clampModelSettings,
  diffModelConfigurations,
} from "@/sections/modals/languageModels/utils";
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
import { getProvider, modelDisplayName } from "@/lib/languageModels/utils";
import {
  useAdminLanguageModels,
  useServerModelSearch,
} from "@/lib/languageModels/hooks";
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
} from "@opal/icons";
import SvgOnyxLogo from "@opal/logos/onyx-logo";
import { Card, EmptyMessageCard } from "@opal/components";
import { ContentAction } from "@opal/layouts";
import type { ContentMdEditHandle } from "@opal/layouts/content/ContentMd";
import { SvgEdit } from "@opal/icons";
import AgentAvatar from "@/refresh-components/avatars/AgentAvatar";
import useUsers from "@/hooks/useUsers";
import { Modal } from "@opal/components";
import { useSettings } from "@/lib/settings/hooks";

/** How long a save may run before the footer says it is taking a while. */
const SLOW_SAVE_NOTICE_MS = 10_000;

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
      ? t("setup.apiBaseField.containerizedNote", {
          appName: settings.appName,
        })
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
          title: g.name,
          description: t("access.groupOption.description"),
        }))
      : [];

  const agentOptions = agents.map((a) => ({
    value: `${AGENT_PREFIX}${a.id}`,
    title: a.name,
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
          <InputSingleSelect
            value={isPublic ? "public" : "private"}
            onValueChange={handleAccessChange}
            defaultOption="public"
            placeholder={t("access.select.placeholder")}
            options={[
              {
                value: "public",
                title: t("access.public.label"),
                icon: SvgOrganization,
              },
              {
                value: "private",
                title: t("access.private.label"),
                icon: SvgUsers,
              },
            ]}
          />
        </InputHorizontal>
      </InputPadder>

      {!isPublic && (
        <Card color="background-tint-00" border="none" padding={2}>
          <Section gap={2}>
            <InputSingleComboBox
              placeholder={t("access.comboBox.placeholder")}
              value=""
              onChange={() => {}}
              onValueChange={handleSelect}
              options={availableOptions}
              searchIcon
            />

            <Card color="background-tint-01" border="none" padding={2}>
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
                      <Card
                        color="background-tint-01"
                        border="none"
                        padding={2}
                      >
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
                      <Card
                        color="background-tint-01"
                        border="none"
                        padding={2}
                      >
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
      icon={isFetching ? IconLoader : SvgRefreshCw}
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

/** Models that ship extra picker metadata (e.g. Nebius TokenFactory). Most
 *  providers do not, and the row description then has no metadata. */
function hasModelMetadata(model: ModelConfiguration): boolean {
  return (
    model.quantization != null ||
    model.country_code != null ||
    (model.supported_features?.length ?? 0) > 0
  );
}

/** Row description. Several ids can share one title, so the model id comes
 *  first when the title is not the id. Metadata such as
 *  "128K · 🇫🇮 · fp8 · tools, reasoning" follows when the model has any. */
function buildModelDescription(model: ModelConfiguration): string | undefined {
  const id = modelDisplayName(model) === model.name ? undefined : model.name;
  if (!hasModelMetadata(model)) return id;
  const parts: string[] = id ? [id] : [];
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

/** The same match the server's model search makes. */
function modelMatchesQuery(model: ModelConfiguration, term: string): boolean {
  return [model.name, model.display_name, model.custom_display_name].some(
    (text) => text?.toLowerCase().includes(term) ?? false
  );
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
              icon={() => <InputCheckbox checked={isSelected} />}
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
  const { defaultText, llmProviders, modelPaging } = useAdminLanguageModels();
  const providerId = formikProps.values.id;
  const [newModelName, setNewModelName] = useState("");
  const [isExpanded, setIsExpanded] = useState(false);
  // When the auto-update toggle is hidden, auto mode should have no effect —
  // otherwise models can't be deselected and "Select All" stays disabled.
  const isAutoMode =
    shouldShowAutoUpdateToggle && formikProps.values.is_auto_mode;
  const models = formikProps.values.model_configurations;

  // The admin listing holds this provider's loaded models and grows as pages
  // and server searches merge in. The form follows it.
  const listedProvider = useMemo(
    () => llmProviders?.find((p) => p.id === providerId),
    [llmProviders, providerId]
  );
  const listedModels = listedProvider?.model_configurations;
  const hasUnloadedModels =
    listedProvider?.next_model_configuration_offset != null;

  // A listed model joins the form once, so a model the provider refetch
  // dropped is not re-added while the listing still shows it.
  const knownNamesRef = useRef(new Set<string>());
  useEffect(() => {
    const known = knownNamesRef.current;
    for (const model of models) known.add(model.name);
    const added = (listedModels ?? []).filter((m) => !known.has(m.name));
    if (added.length === 0) return;
    for (const model of added) known.add(model.name);
    formikProps.setFieldValue("model_configurations", [
      ...models,
      ...added.map(clampModelSettings),
    ]);
  }, [listedModels, models]); // eslint-disable-line react-hooks/exhaustive-deps

  // A search also asks the server while models are unloaded: the admin needs
  // every match to toggle, where a picker needs one to choose.
  const [query, setQuery] = useState("");
  const trimmedQuery = query.trim();
  const isSearching = trimmedQuery !== "";
  const providerIds = useMemo(
    () => (providerId == null ? [] : [providerId]),
    [providerId]
  );
  const serverSearched = useServerModelSearch(
    modelPaging,
    trimmedQuery,
    providerId != null && hasUnloadedModels,
    providerIds
  );

  // The end of the list pages the next window: of the current server
  // search's matches while searching, of the provider's models otherwise.
  const canLoadMore = isSearching
    ? serverSearched && modelPaging.searchHasMore
    : hasUnloadedModels;
  const loadNextWindow = useCallback(() => {
    if (providerId == null || modelPaging.isLoading || !canLoadMore) return;
    if (isSearching) {
      modelPaging.loadMoreSearch().catch(console.error);
      return;
    }
    modelPaging.loadMore([providerId]).catch(console.error);
  }, [modelPaging, providerId, canLoadMore, isSearching]);

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
  const baseModels = isAutoMode ? visibleModels : models;
  const lowerQuery = trimmedQuery.toLowerCase();
  const matchingModels = isSearching
    ? baseModels.filter((m) => modelMatchesQuery(m, lowerQuery))
    : baseModels;
  // Sort by name for providers that ship rich model metadata (Nebius
  // TokenFactory) so the order is stable across refetches. Otherwise keep
  // the given order.
  const displayModels = matchingModels.some((m) => hasModelMetadata(m))
    ? [...matchingModels].sort((a, b) => a.name.localeCompare(b.name))
    : matchingModels;
  // A search shows every match: the fold would hide the ones scrolled for.
  const isFoldable = !isSearching && displayModels.length > FOLD_THRESHOLD;
  const shownModels =
    isFoldable && !isExpanded
      ? displayModels.slice(0, FOLD_THRESHOLD)
      : displayModels;
  const showSearch = models.length > FOLD_THRESHOLD || hasUnloadedModels;
  const showSentinel = canLoadMore && (!isFoldable || isExpanded);
  const defaultModelName =
    providerId != null && defaultText?.provider_id === providerId
      ? defaultText.model_name
      : undefined;

  // Scrolling the sentinel into view loads the next window. The observer is
  // rebuilt when a load settles, so a sentinel still in view after a short
  // page fires again until the list outgrows the box.
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const sentinel = sentinelRef.current;
    if (!sentinel) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) loadNextWindow();
      },
      { rootMargin: "100px" }
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [loadNextWindow, showSentinel]);

  return (
    <Card color="background-tint-00" border="none" padding={2}>
      <Section gap={2}>
        <InputHorizontal
          title={t("models.field.title")}
          description={t("models.field.description")}
          center
        >
          <Section flexDirection="row" gap={0}>
            <Button
              disabled={isAutoMode || models.length === 0 || hasUnloadedModels}
              prominence="tertiary"
              size="md"
              onClick={handleToggleSelectAll}
              tooltip={
                hasUnloadedModels
                  ? t("models.selectAllButton.unloadedTooltip")
                  : undefined
              }
            >
              {allSelected
                ? t("models.deselectAllButton.label")
                : t("models.selectAllButton.label")}
            </Button>
            {onRefetch && <RefetchButton onRefetch={onRefetch} />}
          </Section>
        </InputHorizontal>

        {showSearch && (
          <InputTypeIn
            searchIcon
            clearButton
            placeholder={t("models.search.placeholder")}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        )}

        {models.length === 0 ? (
          <EmptyMessageCard
            title={emptyMessage ?? t("models.empty.title")}
            padding={2}
          />
        ) : displayModels.length === 0 && !modelPaging.isLoading ? (
          <EmptyMessageCard title={t("models.search.noMatch")} padding={2} />
        ) : (
          <Section gap={1} alignItems="stretch">
            {shownModels.map((model) => (
              <ModelRow
                key={model.name}
                model={model}
                isAutoMode={isAutoMode}
                onToggleVisibility={(visible) =>
                  setVisibility(model.name, visible)
                }
                onRename={(value) => setCustomDisplayName(model.name, value)}
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
            {showSentinel && (
              <OpalSection
                ref={sentinelRef}
                data-testid="model-list-sentinel"
                flexDirection="row"
                width="full"
                height="auto"
                padding={0.25}
              >
                {modelPaging.isLoading && <IconLoader size={14} />}
              </OpalSection>
            )}
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
            <InputSwitch
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
  const {
    isValid,
    isSubmitting,
    status,
    setFieldValue,
    values,
    initialValues,
  } = useFormikContext<BaseLLMFormValues>();

  // Paged-in models join the form as the server holds them, which Formik's
  // own dirty flag would count as an edit. Models are judged against the
  // server's copy instead, and the other fields keep Formik's comparison.
  const dirty = useMemo(() => {
    const { model_configurations: formModels, ...formRest } = values;
    const { model_configurations: initialModels, ...initialRest } =
      initialValues;
    if (!isEqual(formRest, initialRest)) return true;
    const { changed } = diffModelConfigurations(formModels, [
      ...initialModels,
      ...(llmProvider?.model_configurations ?? []),
    ]);
    if (changed.length > 0) return true;
    // A server model the form has not taken in yet is no removal, so only
    // the initial models count as dropped.
    const formNames = new Set(formModels.map((m) => m.name));
    return initialModels.some((m) => !formNames.has(m.name));
  }, [values, initialValues, llmProvider]);

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

  // A provider with thousands of models saves in seconds, not instantly, so
  // a long-running submit says so instead of looking stuck.
  const [saveIsSlow, setSaveIsSlow] = useState(false);
  useEffect(() => {
    if (!isSubmitting) {
      setSaveIsSlow(false);
      return;
    }
    const handle = setTimeout(() => setSaveIsSlow(true), SLOW_SAVE_NOTICE_MS);
    return () => clearTimeout(handle);
  }, [isSubmitting]);

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
            {saveIsSlow && (
              <OpalText font="secondary-body" color="text-03">
                {t("setup.slowSave.text")}
              </OpalText>
            )}
            <Button prominence="secondary" onClick={onClose} type="button">
              {t("setup.cancelButton.label")}
            </Button>
            <Button
              disabled={!isValid || !dirty || busy}
              type="submit"
              icon={busy ? IconLoader : undefined}
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
