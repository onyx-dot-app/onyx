"use client";

import { useId, useState, useEffect, useRef } from "react";
import { useTranslations } from "next-intl";
import { useFocusOnMount } from "@opal/hooks";
import {
  Formik,
  Form,
  useFormikContext,
  type FormikHelpers,
  type FormikErrors,
  type FormikProps,
} from "formik";
import * as Yup from "yup";
import isEqual from "lodash/isEqual";
import { InputHorizontal, InputVertical, toast } from "@opal/layouts";
import useSWR, { useSWRConfig } from "swr";
import { useRouter } from "next/navigation";
import { useDefaultAssistantConfiguration } from "@/lib/agents/hooks";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import type { ToolSnapshot } from "@/lib/tools/types";
import { can } from "@/lib/permissions/resource-actions";
import { refreshMemberPluginCaches } from "@/lib/plugins/member";
import { pluginDetailHref, withPluginSearchParams } from "@/lib/plugins/routes";
import { mintMcpChatEnableIntent } from "@/sections/actions/mcpChatEnableIntent";
import PluginAvailabilitySwitch from "@/sections/plugins/PluginAvailabilitySwitch";
import { MCPConnectionStatus, MCPServerStatus } from "@/lib/mcp/types";
import { updateMCPServer } from "@/lib/mcp/svc";
import {
  MCPServerUpdateRequest,
  MCPServer,
  type MCPServerConfigurationValues,
} from "@/lib/mcp/types";
import { useUser } from "@/providers/UserProvider";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import { useTierAtLeast } from "@/lib/tiers/hooks";
import { Tier } from "@/lib/tiers/types";
import { useSettings } from "@/lib/settings/hooks";
import { useUserGroups } from "@/lib/hooks";
import { IconLoader } from "@opal/loaders";
import { Permission } from "@/lib/types";
import {
  Button,
  InputSingleSelect,
  InputTypeIn,
  InputTextArea,
  Text,
  type SelectOption,
} from "@opal/components";
import GroupShareList from "@/lib/connectors/components/GroupShareList";
import { Section } from "@opal/layouts";

import { UserManagementSwitch } from "@/sections/actions/PolicyEditor";
import MCPFormActions from "@/sections/actions/modals/MCPFormActions";
import MCPFormDirtyObserver from "@/sections/actions/modals/MCPFormDirtyObserver";

interface MCPServerDetailsValues extends MCPServerConfigurationValues {
  users_can_manage_policies: boolean;
  // Untouched Chat availability follows the shared configuration cache.
  enabled_in_chat: boolean | undefined;
}

interface MCPServerDetailsPageProps {
  onAuthenticate?: () => void;
  active: boolean;
  variant?: "modal" | "page";
  readOnly?: boolean;
  footerTarget?: HTMLDivElement | null;
  server: MCPServer;
  onSaved: (server: MCPServer) => Promise<void>;
  onBusyChange: (busy: boolean) => void;
  onDirtyChange: (dirty: boolean) => void;
}

export default function MCPServerDetailsPage({
  onAuthenticate,
  active,
  variant = "modal",
  readOnly = false,
  footerTarget = null,
  server,
  onSaved,
  onBusyChange,
  onDirtyChange,
}: MCPServerDetailsPageProps) {
  const formId = useId();
  const formRef = useRef<FormikProps<MCPServerDetailsValues>>(null);
  const t = useTranslations("actions");
  const [isSubmitting, setIsSubmitting] = useState(false);
  useEffect(() => onBusyChange(isSubmitting), [isSubmitting, onBusyChange]);
  const focusOnMount = useFocusOnMount<HTMLInputElement>(
    active && variant === "modal" && !readOnly
  );

  const { user, userResolution } = useUser();
  const router = useRouter();
  const { mutate } = useSWRConfig();
  const defaultChat = useDefaultAssistantConfiguration();
  const {
    data: tools,
    error: toolsError,
    isLoading: toolsLoading,
  } = useSWR<ToolSnapshot[], Error>(
    defaultChat.canEdit
      ? SWR_KEYS.adminMcpServerToolSnapshots(server.id)
      : null,
    errorHandlingFetcher,
    { revalidateOnFocus: false }
  );
  const chatEnabled =
    tools && defaultChat.data
      ? tools.some((tool) => defaultChat.data?.tool_ids.includes(tool.id))
      : server.default_chat_enabled === true;
  const authenticationRequired =
    server.status === MCPServerStatus.AWAITING_AUTH ||
    server.connection_status === MCPConnectionStatus.NOT_CONNECTED ||
    server.connection_status === MCPConnectionStatus.REAUTH_REQUIRED ||
    tools?.length === 0;
  const chatReady =
    !!defaultChat.data && !defaultChat.error && !!tools && !toolsError;

  const { isGlobalHolder, isScopedManager } = usePermissionAuthority(
    Permission.MANAGE_ACTIONS
  );
  const settings = useSettings();
  const businessTier = useTierAtLeast(Tier.BUSINESS);
  const canRestrict = businessTier && settings.enterprise !== null;
  const { isLoading: groupsLoading, error: groupsError } =
    useUserGroups(canRestrict);
  const authorityReady =
    userResolution === "resolved" &&
    !settings.isLoading &&
    (!defaultChat.canEdit || (!defaultChat.isLoading && !toolsLoading)) &&
    (readOnly || isGlobalHolder || isScopedManager);

  const validationSchema = Yup.object().shape({
    name: Yup.string().required(t("addMcpModal.name.required")),
    description: Yup.string(),
  });

  const initialValues: MCPServerDetailsValues = {
    name: server.name,
    description: server.description || "",
    server_url: server.server_url,
    is_public: !readOnly && isScopedManager ? false : server.is_public,
    access_mode:
      (!readOnly && isScopedManager) || server.is_public === false
        ? "groups"
        : "public",
    groups: server.groups,
    users: server.users,
    users_can_manage_policies: server.users_can_manage_policies ?? true,
    available_in_craft: server.available_in_craft === true,
    enabled_in_chat: undefined,
  };

  function hasAccessChanges(values: MCPServerConfigurationValues) {
    return (
      values.is_public !== server.is_public ||
      !isEqual(new Set(values.groups), new Set(server.groups)) ||
      !isEqual(new Set(values.users), new Set(server.users))
    );
  }

  const handleSubmit = async (
    values: MCPServerDetailsValues,
    helpers: FormikHelpers<MCPServerDetailsValues>
  ) => {
    const baseline = formRef.current?.initialValues;
    if (!baseline) return;
    const accessChanged =
      values.is_public !== baseline.is_public ||
      !isEqual(new Set(values.groups), new Set(baseline.groups)) ||
      !isEqual(new Set(values.users), new Set(baseline.users));
    const chatChanged =
      values.enabled_in_chat !== undefined &&
      values.enabled_in_chat !== chatEnabled;
    const needsAuthentication =
      chatChanged && values.enabled_in_chat && authenticationRequired;
    if (
      readOnly ||
      !authorityReady ||
      (chatChanged && (!defaultChat.canEdit || !chatReady)) ||
      (needsAuthentication && !can(server, "authenticate")) ||
      (accessChanged && !values.is_public && !canRestrict) ||
      (accessChanged &&
        values.access_mode === "groups" &&
        (groupsLoading || groupsError))
    )
      return;
    setIsSubmitting(true);

    const payload: MCPServerUpdateRequest = {};
    if (values.name !== baseline.name) payload.name = values.name;
    if (values.description !== baseline.description)
      payload.description = values.description;
    if (
      settings.onyx_craft_available === true &&
      values.users_can_manage_policies !== baseline.users_can_manage_policies
    ) {
      payload.users_can_manage_policies = values.users_can_manage_policies;
    }
    if (
      settings.onyx_craft_available === true &&
      values.available_in_craft !== baseline.available_in_craft
    ) {
      payload.available_in_craft = values.available_in_craft;
    }
    if (accessChanged) {
      payload.is_public = values.is_public;
      payload.groups = values.is_public ? [] : values.groups;
      payload.users = values.is_public ? [] : values.users;
    }

    try {
      const intent = needsAuthentication
        ? mintMcpChatEnableIntent({ userId: user?.id, serverId: server.id })
        : null;
      if (needsAuthentication && !intent)
        throw new Error(t("addMcpModal.toasts.updateFailed"));
      const savedServer = Object.keys(payload).length
        ? await updateMCPServer(server.id, payload)
        : server;
      if (chatChanged && !needsAuthentication && tools) {
        await defaultChat.updateTools(
          tools.map((tool) => tool.id),
          values.enabled_in_chat === true
        );
      }
      await onSaved(savedServer);
      await refreshMemberPluginCaches(mutate);
      helpers.resetForm({ values: { ...values, enabled_in_chat: undefined } });
      if (intent) {
        router.push(
          withPluginSearchParams(
            pluginDetailHref({ kind: "mcp", id: server.id }),
            {
              tab: "authentication",
              enable_chat: "true",
              enable_chat_intent: intent,
            }
          )
        );
        onAuthenticate?.();
      }
    } catch (error) {
      console.error("Error updating MCP server:", error);
      toast.error(
        error instanceof Error
          ? error.message
          : t("addMcpModal.toasts.updateFailed")
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <>
      {!authorityReady ? (
        <Section padding={variant === "page" ? 0 : 6}>
          <IconLoader />
        </Section>
      ) : (
        <Formik<MCPServerDetailsValues>
          innerRef={formRef}
          initialValues={initialValues}
          validationSchema={validationSchema}
          validate={(values) =>
            hasAccessChanges(values)
              ? validateMCPAccess(
                  values,
                  !readOnly && isScopedManager,
                  t("addMcpModal.access.groups.required")
                )
              : {}
          }
          validateOnMount
          onSubmit={handleSubmit}
        >
          {(formikProps) => (
            <Form
              id={formId}
              className="flex min-h-0 min-w-0 w-full flex-1 flex-col gap-6"
            >
              <MCPFormDirtyObserver onDirtyChange={onDirtyChange} />
              <fieldset
                disabled={isSubmitting || readOnly}
                className="min-w-0 w-full"
              >
                <Section
                  gap={6}
                  padding={variant === "page" ? 0 : 6}
                  alignItems="stretch"
                >
                  <InputVertical
                    withLabel="name"
                    title={t("addMcpModal.name.title")}
                  >
                    <InputTypeIn
                      id="name"
                      name="name"
                      value={formikProps.values.name}
                      onChange={formikProps.handleChange}
                      onBlur={formikProps.handleBlur}
                      variant={
                        formikProps.touched.name && formikProps.errors.name
                          ? "error"
                          : "primary"
                      }
                      placeholder={t("addMcpModal.name.placeholder")}
                      ref={focusOnMount}
                    />
                  </InputVertical>

                  <InputVertical
                    withLabel="description"
                    title={t("addMcpModal.description.title")}
                    suffix="optional"
                  >
                    <InputTextArea
                      id="description"
                      name="description"
                      value={formikProps.values.description ?? ""}
                      onChange={formikProps.handleChange}
                      onBlur={formikProps.handleBlur}
                      placeholder={t("addMcpModal.description.placeholder")}
                      rows={2}
                      autoResize
                      maxRows={4}
                    />
                  </InputVertical>

                  <div className="w-full border-t border-border-01 pt-6">
                    <MCPAccessControl
                      isGlobalHolder={readOnly || isGlobalHolder}
                      isScopedManager={!readOnly && isScopedManager}
                      canRestrict={canRestrict}
                      disabled={isSubmitting || readOnly}
                    />
                  </div>
                </Section>
              </fieldset>

              {defaultChat.canEdit && (
                <PluginAvailabilitySwitch
                  surface="chat"
                  enabled={formikProps.values.enabled_in_chat ?? chatEnabled}
                  onChange={(value) =>
                    void formikProps.setFieldValue(
                      "enabled_in_chat",
                      value === chatEnabled ? undefined : value
                    )
                  }
                  disabled={
                    readOnly ||
                    isSubmitting ||
                    !chatReady ||
                    (!chatEnabled &&
                      authenticationRequired &&
                      !can(server, "authenticate"))
                  }
                />
              )}
              {settings.onyx_craft_available === true && (
                <PluginAvailabilitySwitch
                  surface="mcp-craft"
                  enabled={formikProps.values.available_in_craft === true}
                  onChange={(value) =>
                    void formikProps.setFieldValue("available_in_craft", value)
                  }
                  disabled={readOnly || isSubmitting}
                />
              )}
              {settings.onyx_craft_available === true && (
                <UserManagementSwitch
                  value={formikProps.values.users_can_manage_policies}
                  onChange={(value) =>
                    void formikProps.setFieldValue(
                      "users_can_manage_policies",
                      value
                    )
                  }
                  disabled={isSubmitting || readOnly}
                />
              )}
              {!readOnly && (
                <MCPFormActions
                  variant={variant}
                  active={active}
                  footerTarget={footerTarget}
                  submit={
                    <Button
                      disabled={
                        isSubmitting ||
                        !formikProps.isValid ||
                        !formikProps.dirty
                      }
                      type="submit"
                      form={formId}
                    >
                      {t(
                        isSubmitting
                          ? "addMcpModal.submitButton.savingLabel"
                          : "addMcpModal.submitButton.saveLabel"
                      )}
                    </Button>
                  }
                />
              )}
            </Form>
          )}
        </Formik>
      )}
    </>
  );
}

export function validateMCPAccess(
  values: MCPServerConfigurationValues,
  isScopedManager: boolean,
  requiredMessage: string
): FormikErrors<MCPServerConfigurationValues> {
  const needsGroup =
    isScopedManager ||
    (values.access_mode === "groups" && values.users.length === 0);
  return needsGroup && values.groups.length === 0
    ? { groups: requiredMessage }
    : {};
}

interface MCPAccessControlProps {
  isGlobalHolder: boolean;
  isScopedManager: boolean;
  canRestrict: boolean;
  disabled?: boolean;
}

export function MCPAccessControl({
  isGlobalHolder,
  isScopedManager,
  canRestrict,
  disabled = false,
}: MCPAccessControlProps) {
  const t = useTranslations("actions.addMcpModal.access");
  const { values, setValues } =
    useFormikContext<MCPServerConfigurationValues>();
  const options: SelectOption[] = [
    ...(isGlobalHolder
      ? [
          {
            value: "public",
            title: t("public.label"),
            description: t("public.description"),
          },
        ]
      : []),
    {
      value: "groups",
      title: t("groups.label"),
      description: t("groups.description"),
      tag: { title: t("planTag"), color: "blue", size: "md" },
      disabled: !canRestrict,
      tooltip: !canRestrict ? t("planNote") : undefined,
    },
  ];

  return (
    <Section gap={3} alignItems="stretch" height="auto">
      <InputHorizontal
        title={t("title")}
        description={t("description")}
        fillInput
        center
      >
        <InputSingleSelect
          value={values.access_mode}
          defaultOption={isScopedManager ? "groups" : "public"}
          placeholder={t("title")}
          options={options}
          disabled={disabled}
          onValueChange={(mode) => {
            if (mode === "public" && isGlobalHolder) {
              setValues({
                ...values,
                access_mode: mode,
                is_public: true,
                groups: [],
                users: [],
              });
            } else if (mode === "groups" && canRestrict) {
              setValues({ ...values, access_mode: mode, is_public: false });
            }
          }}
        />
      </InputHorizontal>
      {values.access_mode === "groups" && (
        <>
          {isScopedManager && (
            <Text font="secondary-body" color="text-03">
              {t("scoped.description")}
            </Text>
          )}
          <GroupShareList
            variant="pills"
            name="groups"
            label={t("groups.label")}
            placeholder={t("groups.placeholder")}
            requiredTier={Tier.BUSINESS}
            disabled={disabled}
          />
          {values.users.length > 0 && (
            <Text font="secondary-body" color="text-03">
              {t("retainedUsers", { count: values.users.length })}
            </Text>
          )}
        </>
      )}
    </Section>
  );
}
