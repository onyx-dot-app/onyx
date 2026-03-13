"use client";

import { useState, useEffect } from "react";
import { FormikProps } from "formik";
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";
import { useAgents } from "@/hooks/useAgents";
import { useUserGroups } from "@/lib/hooks";
import { ModelConfiguration, SimpleKnownModel } from "@/interfaces/llm";
import * as InputLayouts from "@/layouts/input-layouts";
import Checkbox from "@/refresh-components/inputs/Checkbox";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import InputComboBox from "@/refresh-components/inputs/InputComboBox";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import PasswordInputTypeInField from "@/refresh-components/form/PasswordInputTypeInField";
import Switch from "@/refresh-components/inputs/Switch";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";
import Text from "@/refresh-components/texts/Text";
import { Button as OpalButton, LineItemButton, Tag } from "@opal/components";
import { BaseLLMFormValues } from "@/sections/modals/llmConfig/formUtils";
import { WithoutStyles } from "@opal/types";
import Separator from "@/refresh-components/Separator";
import { Section } from "@/layouts/general-layouts";
import { Disabled, Hoverable } from "@opal/core";
import { Content } from "@opal/layouts";
import {
  SvgOnyxOctagon,
  SvgOrganization,
  SvgRefreshCw,
  SvgSparkle,
  SvgUserManage,
  SvgUsers,
  SvgX,
} from "@opal/icons";
import { NameCard } from "@/refresh-components/cards";
import { Card, EmptyMessageCard } from "@opal/components";
import AgentAvatar from "@/refresh-components/avatars/AgentAvatar";
import useUsers from "@/hooks/useUsers";
import { UserRole } from "@/lib/types";

export function FieldSeparator() {
  return <Separator noPadding className="px-2" />;
}

export type FieldWrapperProps = WithoutStyles<
  React.HTMLAttributes<HTMLDivElement>
>;

export function FieldWrapper(props: FieldWrapperProps) {
  return <div {...props} className="px-2 w-full" />;
}

// ─── DisplayNameField ────────────────────────────────────────────────────────

export interface DisplayNameFieldProps {
  disabled?: boolean;
}

export function DisplayNameField({ disabled = false }: DisplayNameFieldProps) {
  return (
    <FieldWrapper>
      <InputLayouts.Vertical
        name="name"
        title="Display Name"
        subDescription="Used to identify this provider in the app."
        optional
      >
        <InputTypeInField
          name="name"
          placeholder="Display Name"
          variant={disabled ? "disabled" : undefined}
        />
      </InputLayouts.Vertical>
    </FieldWrapper>
  );
}

// ─── APIKeyField ─────────────────────────────────────────────────────────────

export interface APIKeyFieldProps {
  optional?: boolean;
  providerName?: string;
}

export function APIKeyField({
  optional = false,
  providerName,
}: APIKeyFieldProps) {
  return (
    <FieldWrapper>
      <InputLayouts.Vertical
        name="api_key"
        title="API Key"
        subDescription={
          providerName
            ? `Paste your API key from ${providerName} to access your models.`
            : "Paste your API key to access your models."
        }
        optional={optional}
      >
        <PasswordInputTypeInField name="api_key" placeholder="API Key" />
      </InputLayouts.Vertical>
    </FieldWrapper>
  );
}

// ─── SingleDefaultModelField ─────────────────────────────────────────────────

export interface SingleDefaultModelFieldProps {
  placeholder?: string;
}

export function SingleDefaultModelField({
  placeholder = "E.g. gpt-4o",
}: SingleDefaultModelFieldProps) {
  return (
    <InputLayouts.Vertical
      name="default_model_name"
      title="Default Model"
      description="The model to use by default for this provider unless otherwise specified."
    >
      <InputTypeInField name="default_model_name" placeholder={placeholder} />
    </InputLayouts.Vertical>
  );
}

// ─── ModelsAccessField ──────────────────────────────────────────────────────

/** Prefix used to distinguish group IDs from agent IDs in the combobox. */
const GROUP_PREFIX = "group:";
const AGENT_PREFIX = "agent:";

interface ModelsAccessFieldProps<T> {
  formikProps: FormikProps<T>;
}

export function ModelsAccessField<T extends BaseLLMFormValues>({
  formikProps,
}: ModelsAccessFieldProps<T>) {
  const { agents } = useAgents();
  const { data: userGroups, isLoading: userGroupsIsLoading } = useUserGroups();
  const { data: usersData } = useUsers({ includeApiKeys: false });
  const isPaidEnterpriseFeaturesEnabled = usePaidEnterpriseFeaturesEnabled();

  const adminCount =
    usersData?.accepted.filter((u) => u.role === UserRole.ADMIN).length ?? 0;

  const isPublic = formikProps.values.is_public;
  const selectedGroupIds = formikProps.values.groups ?? [];
  const selectedAgentIds = formikProps.values.personas ?? [];

  // Build a flat list of combobox options from groups + agents
  const groupOptions =
    isPaidEnterpriseFeaturesEnabled && !userGroupsIsLoading && userGroups
      ? userGroups.map((g) => ({
          value: `${GROUP_PREFIX}${g.id}`,
          label: g.name,
          description: "Group",
        }))
      : [];

  const agentOptions = agents.map((a) => ({
    value: `${AGENT_PREFIX}${a.id}`,
    label: a.name,
    description: "Agent",
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

  const hasSelections =
    selectedGroupIds.length > 0 || selectedAgentIds.length > 0;

  return (
    <div className="flex flex-col w-full">
      <FieldWrapper>
        <InputLayouts.Horizontal
          name="is_public"
          title="Models Access"
          description="Who can access this provider."
        >
          <InputSelect
            value={isPublic ? "public" : "private"}
            onValueChange={handleAccessChange}
          >
            <InputSelect.Trigger placeholder="Select access level" />
            <InputSelect.Content>
              <InputSelect.Item value="public" icon={SvgOrganization}>
                All Users & Agents
              </InputSelect.Item>
              <InputSelect.Item value="private" icon={SvgUsers}>
                Named Groups & Agents
              </InputSelect.Item>
            </InputSelect.Content>
          </InputSelect>
        </InputLayouts.Horizontal>
      </FieldWrapper>

      {!isPublic && (
        <Card backgroundVariant="light" borderVariant="none" sizeVariant="lg">
          <Section gap={0.5}>
            <InputComboBox
              placeholder="Add groups and agents"
              value=""
              onChange={() => {}}
              onValueChange={handleSelect}
              options={availableOptions}
              strict
              leftSearchIcon
            />

            <NameCard
              icon={SvgUserManage}
              title="Admin"
              description={`${adminCount} ${
                adminCount === 1 ? "member" : "members"
              }`}
              rightChildren={
                <Text secondaryBody text03>
                  Always shared
                </Text>
              }
            />
            {selectedGroupIds.length > 0 && (
              <div className="grid grid-cols-2 gap-1 w-full">
                {selectedGroupIds.map((id) => {
                  const group = groupById.get(id);
                  const memberCount = group?.users.length ?? 0;
                  return (
                    <div key={`group-${id}`} className="min-w-0">
                      <NameCard
                        icon={SvgUsers}
                        title={group?.name ?? `Group ${id}`}
                        description={`${memberCount} ${
                          memberCount === 1 ? "member" : "members"
                        }`}
                        rightChildren={
                          <OpalButton
                            size="sm"
                            prominence="internal"
                            icon={SvgX}
                            onClick={() => handleRemoveGroup(id)}
                            type="button"
                          />
                        }
                      />
                    </div>
                  );
                })}
              </div>
            )}

            <FieldSeparator />

            {selectedAgentIds.length > 0 ? (
              <div className="grid grid-cols-2 gap-1 w-full">
                {selectedAgentIds.map((id) => {
                  const agent = agentMap.get(id);
                  return (
                    <div key={`agent-${id}`} className="min-w-0">
                      <NameCard
                        customIcon={
                          agent ? (
                            <AgentAvatar agent={agent} size={20} />
                          ) : undefined
                        }
                        icon={!agent ? SvgSparkle : undefined}
                        title={agent?.name ?? `Agent ${id}`}
                        description="Agent"
                        rightChildren={
                          <OpalButton
                            size="sm"
                            prominence="internal"
                            icon={SvgX}
                            onClick={() => handleRemoveAgent(id)}
                            type="button"
                          />
                        }
                      />
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="w-full p-2">
                <Content
                  icon={SvgOnyxOctagon}
                  title="No agents added"
                  description="This provider will not be used by any agents."
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

// ─── FetchModelsButton ───────────────────────────────────────────────────────

interface FetchModelsButtonProps {
  onFetch: () => Promise<{ models: ModelConfiguration[]; error?: string }>;
  isDisabled?: boolean;
  disabledHint?: string;
  onModelsFetched: (models: ModelConfiguration[]) => void;
  onLoadingChange?: (isLoading: boolean) => void;
  autoFetchOnInitialLoad?: boolean;
}

export function FetchModelsButton({
  onFetch,
  isDisabled = false,
  disabledHint,
  onModelsFetched,
  onLoadingChange,
  autoFetchOnInitialLoad = false,
}: FetchModelsButtonProps) {
  const [isFetchingModels, setIsFetchingModels] = useState(false);
  const [fetchModelsError, setFetchModelsError] = useState("");

  const handleFetchModels = async () => {
    setIsFetchingModels(true);
    onLoadingChange?.(true);
    setFetchModelsError("");

    try {
      const { models, error } = await onFetch();

      if (error) {
        setFetchModelsError(error);
      } else {
        onModelsFetched(models);
      }
    } catch (err) {
      const errorMessage =
        err instanceof Error ? err.message : "Unknown error occurred";
      setFetchModelsError(errorMessage);
    } finally {
      setIsFetchingModels(false);
      onLoadingChange?.(false);
    }
  };

  // Auto-fetch models on initial load if enabled and not disabled
  useEffect(() => {
    if (autoFetchOnInitialLoad && !isDisabled) {
      handleFetchModels();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="flex flex-col gap-y-1">
      <SimpleTooltip tooltip={isDisabled ? disabledHint : undefined} side="top">
        <div className="w-fit">
          <Disabled disabled={isFetchingModels || isDisabled}>
            <OpalButton type="button" onClick={handleFetchModels}>
              Fetch Available Models
            </OpalButton>
          </Disabled>
        </div>
      </SimpleTooltip>
      {fetchModelsError && (
        <Text as="p" className="text-xs text-status-error-05 mt-1">
          {fetchModelsError}
        </Text>
      )}
    </div>
  );
}

// ─── ModelsField ─────────────────────────────────────────────────────

export interface ModelsFieldProps<T> {
  formikProps: FormikProps<T>;
  modelConfigurations: ModelConfiguration[];
  noModelConfigurationsMessage?: string;
  isLoading?: boolean;
  recommendedDefaultModel: SimpleKnownModel | null;
  shouldShowAutoUpdateToggle: boolean;
  /** Called when the user clicks the refresh button to re-fetch models. */
  onRefetch?: () => void;
}

export function ModelsField<T extends BaseLLMFormValues>({
  formikProps,
  modelConfigurations,
  noModelConfigurationsMessage,
  isLoading,
  recommendedDefaultModel,
  shouldShowAutoUpdateToggle,
  onRefetch,
}: ModelsFieldProps<T>) {
  const isAutoMode = formikProps.values.is_auto_mode;
  const selectedModels = formikProps.values.selected_model_names ?? [];
  const defaultModel = formikProps.values.default_model_name;

  function handleCheckboxChange(modelName: string, checked: boolean) {
    // Read current values inside the handler to avoid stale closure issues
    const currentSelected = formikProps.values.selected_model_names ?? [];
    const currentDefault = formikProps.values.default_model_name;

    if (checked) {
      const newSelected = [...currentSelected, modelName];
      formikProps.setFieldValue("selected_model_names", newSelected);
      // If this is the first model, set it as default
      if (currentSelected.length === 0) {
        formikProps.setFieldValue("default_model_name", modelName);
      }
    } else {
      const newSelected = currentSelected.filter((name) => name !== modelName);
      formikProps.setFieldValue("selected_model_names", newSelected);
      // If removing the default, set the first remaining model as default
      if (currentDefault === modelName && newSelected.length > 0) {
        formikProps.setFieldValue("default_model_name", newSelected[0]);
      } else if (newSelected.length === 0) {
        formikProps.setFieldValue("default_model_name", null);
      }
    }
  }

  function handleSetDefault(modelName: string) {
    formikProps.setFieldValue("default_model_name", modelName);
  }

  function handleToggleAutoMode(nextIsAutoMode: boolean) {
    formikProps.setFieldValue("is_auto_mode", nextIsAutoMode);
    formikProps.setFieldValue(
      "selected_model_names",
      modelConfigurations.filter((m) => m.is_visible).map((m) => m.name)
    );
    formikProps.setFieldValue(
      "default_model_name",
      recommendedDefaultModel?.name ?? null
    );
  }

  const allSelected =
    modelConfigurations.length > 0 &&
    modelConfigurations.every((m) => selectedModels.includes(m.name));

  function handleToggleSelectAll() {
    if (allSelected) {
      formikProps.setFieldValue("selected_model_names", []);
      formikProps.setFieldValue("default_model_name", null);
    } else {
      const allNames = modelConfigurations.map((m) => m.name);
      formikProps.setFieldValue("selected_model_names", allNames);
      if (!formikProps.values.default_model_name && allNames.length > 0) {
        formikProps.setFieldValue("default_model_name", allNames[0]);
      }
    }
  }

  const visibleModels = modelConfigurations.filter((m) => m.is_visible);

  return (
    <Card backgroundVariant="light" borderVariant="none" sizeVariant="lg">
      <Section gap={0.5}>
        <InputLayouts.Horizontal
          title="Models"
          description="Select models to make available for this provider."
          nonInteractive
          center
        >
          <Section flexDirection="row" gap={0}>
            <Disabled disabled={isAutoMode || modelConfigurations.length === 0}>
              <OpalButton
                prominence="tertiary"
                size="md"
                onClick={handleToggleSelectAll}
              >
                {allSelected ? "Unselect All" : "Select All"}
              </OpalButton>
            </Disabled>
            {onRefetch && (
              <OpalButton
                prominence="tertiary"
                icon={SvgRefreshCw}
                onClick={onRefetch}
              />
            )}
          </Section>
        </InputLayouts.Horizontal>

        {modelConfigurations.length === 0 ? (
          <EmptyMessageCard title="No models available." />
        ) : (
          <Section gap={0.25}>
            {isAutoMode
              ? // Auto mode: read-only display
                visibleModels.map((model) => (
                  <Hoverable.Root
                    key={model.name}
                    group="asdf"
                    widthVariant="full"
                  >
                    <LineItemButton
                      variant="section"
                      sizePreset="main-ui"
                      selectVariant="select-heavy"
                      state="selected"
                      icon={() => <Checkbox checked />}
                      title={model.display_name || model.name}
                      rightChildren={
                        model.name === defaultModel ? (
                          <Section>
                            <Tag title="Default Model" color="blue" />
                          </Section>
                        ) : undefined
                      }
                    />
                  </Hoverable.Root>
                ))
              : // Manual mode: checkbox selection
                modelConfigurations.map((modelConfiguration) => {
                  const isSelected = selectedModels.includes(
                    modelConfiguration.name
                  );
                  const isDefault = defaultModel === modelConfiguration.name;

                  return (
                    <Hoverable.Root
                      group="LLMConfigurationButton"
                      widthVariant="full"
                    >
                      <LineItemButton
                        key={modelConfiguration.name}
                        variant="section"
                        sizePreset="main-ui"
                        selectVariant="select-heavy"
                        state={isSelected ? "selected" : "empty"}
                        icon={() => <Checkbox checked={isSelected} />}
                        title={modelConfiguration.name}
                        onClick={() =>
                          handleCheckboxChange(
                            modelConfiguration.name,
                            !isSelected
                          )
                        }
                        rightChildren={
                          isSelected ? (
                            isDefault ? (
                              <Section>
                                <Tag color="blue" title="Default Model" />
                              </Section>
                            ) : (
                              <Hoverable.Item
                                group="LLMConfigurationButton"
                                variant="opacity-on-hover"
                              >
                                <OpalButton
                                  size="sm"
                                  prominence="internal"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    handleSetDefault(modelConfiguration.name);
                                  }}
                                  type="button"
                                >
                                  Set as default
                                </OpalButton>
                              </Hoverable.Item>
                            )
                          ) : undefined
                        }
                      />
                    </Hoverable.Root>
                  );
                })}
          </Section>
        )}

        {shouldShowAutoUpdateToggle && (
          <InputLayouts.Horizontal
            title="Auto Update"
            description="Update the available models when new models are released."
          >
            <Switch
              checked={isAutoMode}
              onCheckedChange={handleToggleAutoMode}
            />
          </InputLayouts.Horizontal>
        )}
      </Section>
    </Card>
  );
}
