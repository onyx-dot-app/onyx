"use client";

import React, { useEffect, useRef, useState } from "react";
import { Formik, Form, useFormikContext } from "formik";
import type { FormikConfig } from "formik";
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";
import { useAgents } from "@/hooks/useAgents";
import { useUserGroups } from "@/lib/hooks";
import { LLMProviderView, ModelConfiguration } from "@/interfaces/llm";
import * as InputLayouts from "@/layouts/input-layouts";
import Checkbox from "@/refresh-components/inputs/Checkbox";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import InputComboBox from "@/refresh-components/inputs/InputComboBox";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import PasswordInputTypeInField from "@/refresh-components/form/PasswordInputTypeInField";
import Switch from "@/refresh-components/inputs/Switch";
import Text from "@/refresh-components/texts/Text";
import { Button, LineItemButton } from "@opal/components";
import { BaseLLMFormValues } from "@/sections/modals/llmConfig/utils";
import type { RichStr } from "@opal/types";
import { Section } from "@/layouts/general-layouts";
import { Content } from "@opal/layouts";
import {
  SvgArrowExchange,
  SvgOnyxOctagon,
  SvgOrganization,
  SvgPlusCircle,
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

// ─── DisplayNameField ────────────────────────────────────────────────────────

export interface DisplayNameFieldProps {
  disabled?: boolean;
}
export function DisplayNameField({ disabled = false }: DisplayNameFieldProps) {
  return (
    <InputLayouts.FieldPadder>
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
    </InputLayouts.FieldPadder>
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
  return (
    <InputLayouts.FieldPadder>
      <InputLayouts.Vertical
        name={name}
        title="API Key"
        subDescription={
          subDescription
            ? subDescription
            : providerName
              ? `Paste your API key from ${providerName} to access your models.`
              : "Paste your API key to access your models."
        }
        suffix={optional ? "optional" : undefined}
      >
        <PasswordInputTypeInField name={name} />
      </InputLayouts.Vertical>
    </InputLayouts.FieldPadder>
  );
}

// ─── APIBaseField ───────────────────────────────────────────────────────────

export interface APIBaseFieldProps {
  optional?: boolean;
  subDescription?: string | RichStr;
  placeholder?: string;
}
export function APIBaseField({
  optional = false,
  subDescription,
  placeholder = "https://",
}: APIBaseFieldProps) {
  return (
    <InputLayouts.FieldPadder>
      <InputLayouts.Vertical
        name="api_base"
        title="API Base URL"
        subDescription={subDescription}
        suffix={optional ? "optional" : undefined}
      >
        <InputTypeInField name="api_base" placeholder={placeholder} />
      </InputLayouts.Vertical>
    </InputLayouts.FieldPadder>
  );
}

// ─── ModelsAccessField ──────────────────────────────────────────────────────

/** Prefix used to distinguish group IDs from agent IDs in the combobox. */
const GROUP_PREFIX = "group:";
const AGENT_PREFIX = "agent:";

export function ModelAccessField() {
  const formikProps = useFormikContext<BaseLLMFormValues>();
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

  return (
    <div className="flex flex-col w-full">
      <InputLayouts.FieldPadder>
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
      </InputLayouts.FieldPadder>

      {!isPublic && (
        <Card background="light" border="none" padding="sm">
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

            <Card background="heavy" border="none" padding="sm">
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
                      <Card background="heavy" border="none" padding="sm">
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

            <InputLayouts.FieldSeparator />

            {selectedAgentIds.length > 0 ? (
              <div className="grid grid-cols-2 gap-1 w-full">
                {selectedAgentIds.map((id) => {
                  const agent = agentMap.get(id);
                  return (
                    <div key={`agent-${id}`} className="min-w-0">
                      <Card background="heavy" border="none" padding="sm">
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

// ─── RefetchButton ──────────────────────────────────────────────────

/**
 * Manages an AbortController so that clicking the button cancels any
 * in-flight fetch before starting a new one. Also aborts on unmount.
 */
interface RefetchButtonProps {
  onRefetch: (signal: AbortSignal) => Promise<void> | void;
}
function RefetchButton({ onRefetch }: RefetchButtonProps) {
  const abortRef = useRef<AbortController | null>(null);
  const [isFetching, setIsFetching] = useState(false);

  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  return (
    <Button
      prominence="tertiary"
      icon={isFetching ? SimpleLoader : SvgRefreshCw}
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
            err instanceof Error ? err.message : "Failed to fetch models"
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

export interface ModelSelectionFieldProps {
  shouldShowAutoUpdateToggle: boolean;
  onRefetch?: (signal: AbortSignal) => Promise<void> | void;
  /** Called when the user adds a custom model by name. Enables the "Add Model" input. */
  onAddModel?: (modelName: string) => void;
}
export function ModelSelectionField({
  shouldShowAutoUpdateToggle,
  onRefetch,
  onAddModel,
}: ModelSelectionFieldProps) {
  const formikProps = useFormikContext<BaseLLMFormValues>();
  const [newModelName, setNewModelName] = useState("");
  const isAutoMode = formikProps.values.is_auto_mode;
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

  function handleToggleAutoMode(nextIsAutoMode: boolean) {
    formikProps.setFieldValue("is_auto_mode", nextIsAutoMode);
    if (nextIsAutoMode) {
      formikProps.setFieldValue(
        "model_configurations",
        originalModelsRef.current
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
    <Card background="light" border="none" padding="sm">
      <Section gap={0.5}>
        <InputLayouts.Horizontal
          title="Models"
          description="Select models to make available for this provider."
          nonInteractive
          center
        >
          <Section flexDirection="row" gap={0}>
            <Button
              disabled={isAutoMode || models.length === 0}
              prominence="tertiary"
              size="md"
              onClick={handleToggleSelectAll}
            >
              {allSelected ? "Unselect All" : "Select All"}
            </Button>
            {onRefetch && <RefetchButton onRefetch={onRefetch} />}
          </Section>
        </InputLayouts.Horizontal>

        {models.length === 0 ? (
          <EmptyMessageCard title="No models available." padding="sm" />
        ) : (
          <Section gap={0.25}>
            {isAutoMode
              ? visibleModels.map((model) => (
                  <LineItemButton
                    key={model.name}
                    variant="section"
                    sizePreset="main-ui"
                    selectVariant="select-heavy"
                    state="selected"
                    icon={() => <Checkbox checked />}
                    title={model.display_name || model.name}
                  />
                ))
              : models.map((model) => (
                  <LineItemButton
                    key={model.name}
                    variant="section"
                    sizePreset="main-ui"
                    selectVariant="select-heavy"
                    state={model.is_visible ? "selected" : "empty"}
                    icon={() => <Checkbox checked={model.is_visible} />}
                    title={model.name}
                    onClick={() => setVisibility(model.name, !model.is_visible)}
                  />
                ))}
          </Section>
        )}

        {onAddModel && !isAutoMode && (
          <Section flexDirection="row" gap={0.5}>
            <div className="flex-1">
              <InputTypeIn
                placeholder="Enter model name"
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
                showClearButton={false}
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
              Add Model
            </Button>
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
}
export function ModalWrapper<T extends BaseLLMFormValues = BaseLLMFormValues>({
  providerName,
  llmProvider,
  onClose,
  initialValues,
  validationSchema,
  onSubmit,
  children,
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
}
function ModalWrapperInner({
  providerName,
  llmProvider,
  onClose,
  modelConfigurations,
  children,
}: ModalWrapperInnerProps) {
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
  const providerIcon = getProviderIcon(providerName);
  const providerDisplayName = getProviderDisplayName(providerName);
  const providerProductName = getProviderProductName(providerName);

  const title = llmProvider
    ? `Configure "${llmProvider.name}"`
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
          <Modal.Body padding={0.5} gap={0}>
            {children}
          </Modal.Body>
          <Modal.Footer>
            <Button prominence="secondary" onClick={onClose} type="button">
              Cancel
            </Button>
            <Button
              disabled={!isValid || !dirty || busy}
              type="submit"
              icon={busy ? SimpleLoader : undefined}
            >
              {llmProvider?.name
                ? busy
                  ? "Updating"
                  : "Update"
                : busy
                  ? "Connecting"
                  : "Connect"}
            </Button>
          </Modal.Footer>
        </Form>
      </Modal.Content>
    </Modal>
  );
}
