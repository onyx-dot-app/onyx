"use client";

import { IconLoader } from "@opal/loaders";
import React, { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Formik, Form, getIn, useFormikContext } from "formik";
import type { FormikConfig } from "formik";
import { cn, countryCodeToFlag } from "@opal/utils";
import { markdown } from "@opal/utils";
import { Hoverable, Interactive } from "@opal/core";
import { useTierAtLeast } from "@/lib/tiers/hooks";
import { Tier } from "@/lib/tiers/types";
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
import { Button } from "@opal/components";
import { Text } from "@opal/components";
import { BaseLLMFormValues } from "@/sections/modals/languageModels/utils";
import type { RichStr } from "@opal/types";
import {
  Content,
  InputDivider,
  InputHorizontal,
  InputPadder,
  InputVertical,
  Section as OpalSection,
  toast,
  Section,
} from "@opal/layouts";
import {
  ModelSettingsPopover,
  type ModelSettingsPatch,
} from "@/sections/modals/languageModels/ModelSettingsPopover";
import { setDefaultLlmModelAndRefresh } from "@/lib/languageModels/cache";
import { getProvider } from "@/lib/languageModels/utils";
import {
  useAdminLanguageModels,
  useModelDisplayName,
} from "@/lib/languageModels/hooks";
import { useProviderNames } from "@/lib/languageModels/useProviderNames";
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
import { Card, EmptyMessageCard, type BadgeProps } from "@opal/components";
import { useModelTypeBadge } from "@/lib/badges/components";
import { ContentAction } from "@opal/layouts";
import type { ContentEditHandle } from "@opal/layouts";
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
  const { initialValues } = useFormikContext<BaseLLMFormValues>();
  // On edit, the initial value is the backend's masked stored key.
  const storedValue: unknown = getIn(initialValues, name);
  const existingValue =
    typeof storedValue === "string" && storedValue ? storedValue : undefined;
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
        <PasswordInputTypeInField name={name} existingValue={existingValue} />
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
  placeholder,
  rightChildren,
}: APIBaseFieldProps) {
  const t = useTranslations("admin.languageModels.modals");
  const tPlaceholders = useTranslations("common.placeholders");
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
          placeholder={placeholder ?? tPlaceholders("url")}
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
                font="main-ui-action"
                icon={SvgUserManage}
                title={t("access.admin.title")}
                description={t("access.memberCount.label", {
                  count: adminCount,
                })}
                rightChildren={
                  <Text font="secondary-body" color="text-03">
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
                  const memberCount = group?.member_count ?? 0;
                  return (
                    <div key={`group-${id}`} className="min-w-0">
                      <Card
                        color="background-tint-01"
                        border="none"
                        padding={2}
                      >
                        <ContentAction
                          font="main-ui-action"
                          icon={SvgUsers}
                          title={group?.name ?? t("access.group.name", { id })}
                          description={t("access.memberCount.label", {
                            count: memberCount,
                          })}
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
                          font="main-ui-action"
                          icon={
                            agent
                              ? () => <AgentAvatar agent={agent} size={20} />
                              : SvgSparkle
                          }
                          title={agent?.name ?? t("access.agent.name", { id })}
                          description={t("access.agentOption.description")}
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
                  font="main-ui-action"
                  icon={SvgOnyxOctagon}
                  title={t("access.noAgents.title")}
                  description={t("access.noAgents.description")}
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
export function RefetchButton({ onRefetch }: RefetchButtonProps) {
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
      aria-label={t("models.refetch.label")}
      tooltip={t("models.refetch.label")}
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

const FOLDED_MIN_MODELS = 3;
const FOLDED_MAX_MODELS = 10;

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

/** Models that ship extra picker metadata (e.g. Nebius TokenFactory). Most
 *  providers do not, and the row description then has no metadata. */
function hasModelMetadata(model: ModelConfiguration): boolean {
  return (
    model.quantization != null ||
    model.country_code != null ||
    (model.supported_features?.length ?? 0) > 0
  );
}

/** Selected models first. Providers that ship rich metadata (Nebius
 *  TokenFactory) sort by id so refetches keep the order. */
function inherentOrder(models: ModelConfiguration[]): string[] {
  const sortByName = models.some((m) => hasModelMetadata(m));
  return [...models]
    .sort(
      (a, b) =>
        Number(b.is_visible) - Number(a.is_visible) ||
        (sortByName ? a.name.localeCompare(b.name) : 0)
    )
    .map((m) => m.name);
}

interface ModelListLayout {
  order: string[];
  foldedCount: number;
  sortedByName: boolean;
}

/** Rows only move on open, fold and unfold, never on a checkbox change. */
function foldedLayout(models: ModelConfiguration[]): ModelListLayout {
  const selected = models.filter((m) => m.is_visible).length;
  return {
    order: inherentOrder(models),
    sortedByName: models.some((m) => hasModelMetadata(m)),
    foldedCount: Math.min(
      Math.max(selected, FOLDED_MIN_MODELS),
      FOLDED_MAX_MODELS
    ),
  };
}

/** Row description. Several ids can share one title, so the model id comes
 *  first when the title is not the id. Metadata such as
 *  "128K · 🇫🇮 · fp8 · tools, reasoning" follows when the model has any. */

function buildModelDescription(
  model: ModelConfiguration,
  displayName: string
): string | undefined {
  const id = displayName === model.name ? undefined : model.name;
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

interface ModelRowProps {
  model: ModelConfiguration;
  isDefaultModel: boolean;
  onToggleVisibility: (visible: boolean) => void;
  onRename: (value: string | null) => void;
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
  isDefaultModel,
  onToggleVisibility,
  onRename,
  onSettingsChange,
  onSetDefaultModel,
}: ModelRowProps) {
  const t = useTranslations("admin.languageModels.modals");
  const editHandle = useRef<ContentEditHandle>(null);
  // Keeps the hover-revealed actions visible while the settings popover,
  // which is portaled outside the row, is open.
  const [settingsOpen, setSettingsOpen] = useState(false);
  const displayName = useModelDisplayName()(model);
  const description = buildModelDescription(model, displayName);
  const decisionBadge = useModelTypeBadge("decision");
  const visionBadge = useModelTypeBadge("vision");
  const modelTypeBadges: BadgeProps[] = [
    ...(model.supports_decisions
      ? [
          {
            ...decisionBadge,
            tooltip: t(
              model.supports_chat === false
                ? "models.row.decisionTag.decisionOnly"
                : "models.row.decisionTag.chatAndDecision"
            ),
          },
        ]
      : []),
    ...(model.supports_image_input ? [visionBadge] : []),
  ];
  const isSelected = model.is_visible;
  const toggleVisibility = () => onToggleVisibility(!model.is_visible);
  // A click that blurs and commits an inline rename reaches the row after the
  // edit input unmounts, so the input's presence is sampled at pointerdown.
  const renamingAtPointerDown = useRef(false);
  // The row is clickable, but it also hosts real buttons (rename, settings).
  // Their clicks, including ones the browser synthesizes from Enter, must not
  // toggle the model.
  const toggleFromRow = (e: React.MouseEvent) => {
    if (renamingAtPointerDown.current) return;
    const interactive = (e.target as HTMLElement).closest(
      'button, input, textarea, [contenteditable="true"]'
    );
    if (interactive) return;
    toggleVisibility();
  };

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
            e.currentTarget.querySelector(".opal-content-title-row input") !=
            null;
        }}
        onClick={toggleFromRow}
        role="button"
        tabIndex={0}
        onKeyDown={(e: React.KeyboardEvent) => {
          // Only the row itself. React bubbles events from portaled
          // children too, so a key inside the settings popover would
          // otherwise toggle the model.
          if (e.target !== e.currentTarget) return;
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            toggleVisibility();
          }
        }}
      >
        <Interactive.Container width="full" size="fit" rounding={3}>
          <OpalSection alignItems="stretch" height="auto" padding={1.5}>
            <ContentAction
              font="main-ui-action"
              color="interactive"
              center
              icon={() => <InputCheckbox checked={isSelected} />}
              title={displayName}
              description={description}
              badge={modelTypeBadges}
              rightChildren={
                <OpalSection
                  flexDirection="row"
                  width="fit"
                  height="auto"
                  gap={1}
                >
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
                      {model.supports_chat !== false && (
                        <ModelSettingsPopover
                          model={model}
                          onChange={onSettingsChange}
                          onOpenChange={setSettingsOpen}
                        />
                      )}
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
                    <span className="px-1.5">
                      <Text
                        as="p"
                        font="secondary-action"
                        wordWrap="whitespace-nowrap"
                        color="action-selection-05"
                      >
                        {t("models.row.defaultLabel")}
                      </Text>
                    </span>
                  )}
                </OpalSection>
              }
              editable
              editHandle={editHandle}
              onTitleChange={(newTitle) => onRename(newTitle || null)}
              padding={0}
            />
          </OpalSection>
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
  const { defaultText } = useAdminLanguageModels();
  const resolveDisplayName = useModelDisplayName();
  const providerId = formikProps.values.id;
  const [newModelName, setNewModelName] = useState("");
  const [isExpanded, setIsExpanded] = useState(false);
  const models = formikProps.values.model_configurations;
  const [layout, setLayout] = useState<ModelListLayout | null>(null);
  // Models the admin types in stay where they appear; a refetch re-sorts.
  const [typedNames, setTypedNames] = useState<Set<string>>(new Set());
  useEffect(() => {
    if (models.length === 0) return;
    const known = new Set(layout?.order);
    if (
      layout === null ||
      layout.sortedByName !== models.some((m) => hasModelMetadata(m)) ||
      models.some((m) => !known.has(m.name) && !typedNames.has(m.name))
    ) {
      setLayout(foldedLayout(models));
    }
  }, [models, layout, typedNames]);

  const addModel =
    onAddModel &&
    ((name: string) => {
      setTypedNames((prev) => new Set(prev).add(name));
      onAddModel(name);
    });

  function toggleExpanded() {
    if (isExpanded) {
      setLayout(foldedLayout(models));
    } else if (layout) {
      // Rows already on screen keep their place; the rest go below them.
      const known = new Set(layout.order);
      const shown = [
        ...layout.order.slice(0, layout.foldedCount),
        ...models.map((m) => m.name).filter((name) => !known.has(name)),
      ];
      const shownSet = new Set(shown);
      setLayout({
        order: [
          ...shown,
          ...inherentOrder(models).filter((name) => !shownSet.has(name)),
        ],
        foldedCount: layout.foldedCount,
        sortedByName: layout.sortedByName,
      });
    }
    setIsExpanded(!isExpanded);
  }

  useEffect(() => {
    const testModel = models.find((model) => model.is_visible)?.name;
    if (testModel !== formikProps.values.test_model_name) {
      formikProps.setFieldValue("test_model_name", testModel);
    }
  }, [models, formikProps.setFieldValue, formikProps.values.test_model_name]);

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

  // A cleared name is null, as the API sends it, so clearing a new name is
  // not a change.
  function setCustomDisplayName(modelName: string, value: string | null) {
    const updated = models.map((m) => {
      if (m.name !== modelName) return m;
      const renamed = { ...m, custom_display_name: value || null };
      return { ...renamed, effectiveDisplayName: resolveDisplayName(renamed) };
    });
    formikProps.setFieldValue("model_configurations", updated);
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
              disabled={models.length === 0}
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
              const { order, foldedCount } = layout ?? foldedLayout(models);
              const byName = new Map(models.map((m) => [m.name, m]));
              const ordered = order.flatMap((name) => byName.get(name) ?? []);
              // Models added since the last re-sort, e.g. a custom model.
              const known = new Set(order);
              const added = models.filter((m) => !known.has(m.name));
              const isFoldable = ordered.length > foldedCount;
              const shownModels = [
                ...(isFoldable && !isExpanded
                  ? ordered.slice(0, foldedCount)
                  : ordered),
                ...added,
              ];
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
                        providerId != null &&
                        model.is_visible &&
                        model.supports_chat !== false
                          ? () => void setDefaultModel(model.name)
                          : undefined
                      }
                    />
                  ))}
                  {isFoldable && (
                    <Interactive.Stateless
                      prominence="tertiary"
                      onClick={toggleExpanded}
                    >
                      <Interactive.Container type="button" width="full">
                        <Content
                          font="secondary-body"
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

        {onAddModel && (
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
                      addModel?.(trimmed);
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
                  addModel?.(trimmed);
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
              checked={formikProps.values.is_auto_mode}
              onCheckedChange={(checked) =>
                formikProps.setFieldValue("is_auto_mode", checked)
              }
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
  }, [modelConfigurations, setFieldValue, values.model_configurations]);

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

  const providerEntry = getProvider(providerName);
  const providerIcon = providerEntry.icon;
  const { companyName: providerDisplayName, productName: providerProductName } =
    useProviderNames()(providerEntry);

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
              <Text font="secondary-body" color="text-03">
                {t("setup.slowSave.text")}
              </Text>
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
