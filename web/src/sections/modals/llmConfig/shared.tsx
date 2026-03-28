"use client";

import { ReactNode } from "react";
import { Form, FormikProps } from "formik";
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
import Text from "@/refresh-components/texts/Text";
import { Button, LineItemButton, Tag } from "@opal/components";
import { BaseLLMFormValues } from "@/sections/modals/llmConfig/utils";
import { WithoutStyles } from "@opal/types";
import Separator from "@/refresh-components/Separator";
import { Section } from "@/layouts/general-layouts";
import { Disabled, Hoverable } from "@opal/core";
import { Content } from "@opal/layouts";
import {
  SvgArrowExchange,
  SvgOnyxOctagon,
  SvgOrganization,
  SvgRefreshCw,
  SvgSparkle,
  SvgUserManage,
  SvgUsers,
  SvgX,
} from "@opal/icons";
import SvgOnyxLogo from "@opal/icons/onyx-logo";
import { Card, EmptyMessageCard } from "@opal/components";
import { ContentAction } from "@opal/layouts";
import AgentAvatar from "@/refresh-components/avatars/AgentAvatar";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import useUsers from "@/hooks/useUsers";
import { toast } from "@/hooks/useToast";
import { UserRole } from "@/lib/types";
import Modal from "@/refresh-components/Modal";
import {
  getProviderIcon,
  getProviderDisplayName,
  getProviderProductName,
} from "@/lib/llmConfig/providers";

export function FieldSeparator() {
  return <Separator noPadding className="px-2" />;
}

export type FieldWrapperProps = WithoutStyles<
  React.HTMLAttributes<HTMLDivElement>
>;

export function FieldWrapper(props: FieldWrapperProps) {
  return <div {...props} className="p-2 w-full" />;
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
        suffix={optional ? "optional" : undefined}
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

            <Card backgroundVariant="heavy" borderVariant="none">
              <ContentAction
                icon={SvgUserManage}
                title="Admin"
                description={`${adminCount} ${
                  adminCount === 1 ? "member" : "members"
                }`}
                sizePreset="main-ui"
                variant="section"
                rightChildren={
                  <Text secondaryBody text03>
                    Always shared
                  </Text>
                }
                paddingVariant="fit"
              />
            </Card>
            {selectedGroupIds.length > 0 && (
              <div className="grid grid-cols-2 gap-1 w-full">
                {selectedGroupIds.map((id) => {
                  const group = groupById.get(id);
                  const memberCount = group?.users.length ?? 0;
                  return (
                    <div key={`group-${id}`} className="min-w-0">
                      <Card backgroundVariant="heavy" borderVariant="none">
                        <ContentAction
                          icon={SvgUsers}
                          title={group?.name ?? `Group ${id}`}
                          description={`${memberCount} ${
                            memberCount === 1 ? "member" : "members"
                          }`}
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
                          paddingVariant="fit"
                        />
                      </Card>
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
                      <Card backgroundVariant="heavy" borderVariant="none">
                        <ContentAction
                          icon={
                            agent
                              ? () => <AgentAvatar agent={agent} size={20} />
                              : SvgSparkle
                          }
                          title={agent?.name ?? `Agent ${id}`}
                          description="Agent"
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
                          paddingVariant="fit"
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

// ─── ModelsField ─────────────────────────────────────────────────────

export interface ModelsFieldProps<T> {
  formikProps: FormikProps<T>;
  modelConfigurations: ModelConfiguration[];
  recommendedDefaultModel: SimpleKnownModel | null;
  shouldShowAutoUpdateToggle: boolean;
  /** Called when the user clicks the refresh button to re-fetch models. */
  onRefetch?: () => Promise<void> | void;
}

export function ModelsField<T extends BaseLLMFormValues>({
  formikProps,
  modelConfigurations,
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
        formikProps.setFieldValue("default_model_name", undefined);
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
      recommendedDefaultModel?.name ?? undefined
    );
  }

  const allSelected =
    modelConfigurations.length > 0 &&
    modelConfigurations.every((m) => selectedModels.includes(m.name));

  function handleToggleSelectAll() {
    if (allSelected) {
      formikProps.setFieldValue("selected_model_names", []);
      formikProps.setFieldValue("default_model_name", undefined);
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
              <Button
                prominence="tertiary"
                size="md"
                onClick={handleToggleSelectAll}
              >
                {allSelected ? "Unselect All" : "Select All"}
              </Button>
            </Disabled>
            {onRefetch && (
              <Button
                prominence="tertiary"
                icon={SvgRefreshCw}
                onClick={async () => {
                  try {
                    await onRefetch();
                  } catch (err) {
                    toast.error(
                      err instanceof Error
                        ? err.message
                        : "Failed to fetch models"
                    );
                  }
                }}
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
                    group="LLMConfigurationButton"
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
                      key={modelConfiguration.name}
                      group="LLMConfigurationButton"
                      widthVariant="full"
                    >
                      <LineItemButton
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
                                <Button
                                  size="sm"
                                  prominence="internal"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    handleSetDefault(modelConfiguration.name);
                                  }}
                                  type="button"
                                >
                                  Set as default
                                </Button>
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

// ============================================================================
// LLMConfigurationModalWrapper
// ============================================================================

interface LLMConfigurationModalWrapperProps {
  providerEndpoint: string;
  providerName?: string;
  existingProviderName?: string;
  onClose: () => void;
  isFormValid: boolean;
  isDirty?: boolean;
  isTesting?: boolean;
  isSubmitting?: boolean;
  children: ReactNode;
}

export function LLMConfigurationModalWrapper({
  providerEndpoint,
  providerName,
  existingProviderName,
  onClose,
  isFormValid,
  isDirty,
  isTesting,
  isSubmitting,
  children,
}: LLMConfigurationModalWrapperProps) {
  const busy = isTesting || isSubmitting;
  const providerIcon = getProviderIcon(providerEndpoint);
  const providerDisplayName =
    providerName ?? getProviderDisplayName(providerEndpoint);
  const providerProductName = getProviderProductName(providerEndpoint);

  const title = existingProviderName
    ? `Configure "${existingProviderName}"`
    : `Set up ${providerProductName}`;
  const description = `Connect to ${providerDisplayName} and set up your ${providerProductName} models.`;

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
          <Modal.Body padding={0.5} gap={0.5}>
            {children}
          </Modal.Body>
          <Modal.Footer>
            <Button prominence="secondary" onClick={onClose} type="button">
              Cancel
            </Button>
            <Disabled
              disabled={
                !isFormValid || busy || (!!existingProviderName && !isDirty)
              }
            >
              <Button type="submit" icon={busy ? SimpleLoader : undefined}>
                {existingProviderName
                  ? busy
                    ? "Updating"
                    : "Update"
                  : busy
                    ? "Connecting"
                    : "Connect"}
              </Button>
            </Disabled>
          </Modal.Footer>
        </Form>
      </Modal.Content>
    </Modal>
  );
}
