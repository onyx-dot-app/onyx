"use client";

import { useId, useState, useEffect, useRef, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { useFocusOnMount } from "@opal/hooks";
import {
  Formik,
  Form,
  useFormikContext,
  type FormikHelpers,
  type FormikErrors,
} from "formik";
import * as Yup from "yup";
import { InputHorizontal, InputVertical, toast } from "@opal/layouts";
import { createMCPServer, updateMCPServer } from "@/lib/mcp/svc";
import { MCPServerCreateRequest, MCPServer } from "@/lib/mcp/types";
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

import MCPFormActions from "@/sections/actions/modals/MCPFormActions";
import MCPFormDirtyObserver from "@/sections/actions/modals/MCPFormDirtyObserver";

interface MCPServerDetailsPageProps {
  active: boolean;
  variant?: "modal" | "page";
  readOnly?: boolean;
  afterFields?: ReactNode;
  onBeforeUrlChange?: () => Promise<boolean>;
  editOnly?: boolean;
  footerTarget?: HTMLDivElement | null;
  server: MCPServer | null;
  onSaved: (server: MCPServer, advance: boolean) => Promise<void>;
  onBusyChange: (busy: boolean) => void;
  onDirtyChange: (dirty: boolean) => void;
  onClose?: () => void;
  onDelete?: () => void;
  mutateMcpServers?: () => Promise<void>;
}

export default function MCPServerDetailsPage({
  active,
  variant = "modal",
  readOnly = false,
  afterFields,
  onBeforeUrlChange,
  editOnly = false,
  footerTarget = null,
  server,
  onSaved,
  onBusyChange,
  onDirtyChange,
  onClose,
  onDelete,
  mutateMcpServers,
}: MCPServerDetailsPageProps) {
  const formId = useId();
  const t = useTranslations("actions");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const advanceAfterSave = useRef(variant === "modal" && !editOnly);
  useEffect(() => onBusyChange(isSubmitting), [isSubmitting, onBusyChange]);
  const focusOnMount = useFocusOnMount<HTMLInputElement>(
    active && variant === "modal" && !readOnly
  );

  const { userResolution } = useUser();
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
    (readOnly || isGlobalHolder || isScopedManager);

  const validationSchema = Yup.object().shape({
    name: Yup.string().required(t("addMcpModal.name.required")),
    description: Yup.string(),
    server_url: Yup.string()
      .url(t("addMcpModal.serverUrl.invalid"))
      .required(t("addMcpModal.serverUrl.required")),
  });

  const isEditMode = !!server;

  const initialValues: MCPServerFormValues = {
    name: server?.name || "",
    description: server?.description || "",
    server_url: server?.server_url || "",
    is_public:
      !readOnly && isScopedManager
        ? false
        : (server?.is_public ?? isGlobalHolder),
    access_mode:
      (!readOnly && isScopedManager) || server?.is_public === false
        ? "groups"
        : "public",
    groups: server?.groups ?? [],
    users: server?.users ?? [],
    available_in_craft: server
      ? (server.available_in_craft ?? false)
      : settings.onyx_craft_available === true,
  };

  const handleSubmit = async (
    values: MCPServerFormValues,
    helpers: FormikHelpers<MCPServerFormValues>
  ) => {
    if (
      readOnly ||
      !authorityReady ||
      (!values.is_public && !canRestrict) ||
      (values.access_mode === "groups" && (groupsLoading || groupsError))
    )
      return;
    setIsSubmitting(true);

    // A public server has no group restriction.
    const payload: MCPServerCreateRequest = {
      name: values.name,
      description: values.description,
      server_url: values.server_url,
      is_public: values.is_public,
      groups: values.is_public ? [] : values.groups,
      users: values.is_public ? [] : values.users,
      ...(!server && {
        available_in_craft: values.available_in_craft,
      }),
    };

    try {
      if (
        server &&
        values.server_url !== server.server_url &&
        onBeforeUrlChange &&
        !(await onBeforeUrlChange())
      )
        return;
      const unchanged =
        server && JSON.stringify(values) === JSON.stringify(initialValues);
      const savedServer = unchanged
        ? server
        : server
          ? await updateMCPServer(server.id, payload)
          : await createMCPServer(payload);
      helpers.resetForm({ values });
      await onSaved(savedServer, advanceAfterSave.current);
      await mutateMcpServers?.().catch((error: unknown) => {
        console.error("Error refreshing MCP servers:", error);
      });
    } catch (error) {
      console.error(
        `Error ${isEditMode ? "updating" : "creating"} MCP server:`,
        error
      );
      toast.error(
        error instanceof Error
          ? error.message
          : isEditMode
            ? t("addMcpModal.toasts.updateFailed")
            : t("addMcpModal.toasts.createFailed")
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  const deleteAction = onDelete && (
    <Button
      prominence="tertiary"
      variant="danger"
      type="button"
      disabled={isSubmitting || readOnly}
      onClick={onDelete}
    >
      {t("mcpCard.deleteModal.submitButton.label")}
    </Button>
  );

  return (
    <>
      {!authorityReady ? (
        <Section padding={variant === "page" ? 0 : 6}>
          <IconLoader />
        </Section>
      ) : (
        <Formik<MCPServerFormValues>
          initialValues={initialValues}
          validationSchema={validationSchema}
          validate={(values) =>
            validateMCPAccess(
              values,
              !readOnly && isScopedManager,
              t("addMcpModal.access.groups.required")
            )
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
                    withLabel="server_url"
                    title={t("addMcpModal.serverUrl.title")}
                  >
                    <InputTypeIn
                      id="server_url"
                      name="server_url"
                      type="url"
                      value={formikProps.values.server_url}
                      onChange={formikProps.handleChange}
                      onBlur={formikProps.handleBlur}
                      variant={
                        formikProps.touched.server_url &&
                        formikProps.errors.server_url
                          ? "error"
                          : "primary"
                      }
                      placeholder="https://your-mcp-server.com/mcp"
                    />
                  </InputVertical>

                  <InputVertical
                    withLabel="description"
                    title={t("addMcpModal.description.title")}
                    suffix={t("addMcpModal.description.suffix")}
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

                  {afterFields}

                  {variant === "modal" && deleteAction}
                </Section>
              </fieldset>

              {!readOnly && (
                <MCPFormActions
                  variant={variant}
                  active={active}
                  footerTarget={footerTarget}
                  leading={deleteAction}
                  cancel={
                    <Button
                      disabled={isSubmitting}
                      prominence="secondary"
                      type="button"
                      onClick={onClose}
                    >
                      {t("addMcpModal.cancelButton.label")}
                    </Button>
                  }
                  submit={
                    <Button
                      disabled={
                        isSubmitting ||
                        !formikProps.isValid ||
                        ((editOnly || variant === "page") && !formikProps.dirty)
                      }
                      type="submit"
                      form={formId}
                      onClick={() => {
                        advanceAfterSave.current =
                          variant === "modal" && !editOnly;
                      }}
                    >
                      {isSubmitting
                        ? t("addMcpModal.submitButton.savingLabel")
                        : t(
                            editOnly || variant === "page"
                              ? "addMcpModal.submitButton.saveLabel"
                              : "mcpSetup.continue"
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

export interface MCPServerFormValues extends MCPServerCreateRequest {
  access_mode: "public" | "groups";
}

export function validateMCPAccess(
  values: MCPServerFormValues,
  isScopedManager: boolean,
  requiredMessage: string
): FormikErrors<MCPServerFormValues> {
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

/** MCP grants allow attaching tools to agents; they do not grant agent access. */
export function MCPAccessControl({
  isGlobalHolder,
  isScopedManager,
  canRestrict,
  disabled = false,
}: MCPAccessControlProps) {
  const t = useTranslations("actions.addMcpModal.access");
  const { values, setValues } = useFormikContext<MCPServerFormValues>();
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
      disabled: !canRestrict,
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
      {!canRestrict && (
        <Text font="secondary-body" color="text-03">
          {t("planNote")}
        </Text>
      )}
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
