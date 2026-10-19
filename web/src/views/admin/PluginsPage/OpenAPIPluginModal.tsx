"use client";

import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type MutableRefObject,
} from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Formik, useFormikContext, type FormikHelpers } from "formik";
import * as Yup from "yup";
import isEqual from "lodash/isEqual";
import useSWR, { useSWRConfig } from "swr";
import {
  Button,
  Divider,
  InputTextArea,
  Modal,
  Tabs,
  Text,
} from "@opal/components";
import {
  Content,
  InputHorizontal,
  InputPadder,
  InputVertical,
  toast,
} from "@opal/layouts";
import { InputSwitchField } from "@opal/form";
import { IconLoader } from "@opal/loaders";
import { markdown } from "@opal/utils";
import useOpenApiTools from "@/hooks/useOpenApiTools";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import InputTextAreaField from "@/refresh-components/form/InputTextAreaField";
import { can } from "@/lib/permissions/resource-actions";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { pluginDetailHref, withPluginSearchParams } from "@/lib/plugins/routes";
import { createCustomTool, updateCustomTool } from "@/lib/plugins/openapi/svc";
import { updateToolStatus } from "@/lib/tools/svc";
import { useDefaultAssistantConfiguration } from "@/lib/agents/hooks";
import { refreshMemberPluginCaches } from "@/lib/plugins/member";
import { extractMethodSpecsFromDefinition } from "@/lib/tools/utils";
import type { OAuthConfig, ToolSnapshot } from "@/lib/tools/types";
import type { OpenAPIPluginFormValues } from "@/lib/plugins/openapi/types";
import {
  newOpenApiAuthValues,
  savedOpenApiAuthValues,
} from "@/lib/plugins/openapi/auth";
import type { CheckedOpenApiSchema } from "@/lib/plugins/openapi/schema";
import { useOpenApiSchemaCheck } from "@/lib/plugins/openapi/hooks";
import { saveOpenApiAuthentication } from "@/lib/plugins/openapi/workflow";
import OpenAPIEndpointList from "@/sections/plugins/OpenAPIEndpointList";
import PluginModalContent from "@/sections/plugins/PluginModalContent";
import OpenAPISchemaFields from "@/views/admin/PluginsPage/components/OpenAPISchemaFields";
import OpenAPIAuthFields, {
  useOpenApiAuthSchema,
} from "@/views/admin/PluginsPage/components/OpenAPIAuthFields";
import { PLUGIN_KIND_ICONS } from "@/lib/plugins/constants";

type Tab = "server" | "schema" | "authentication";

interface OpenAPIPluginModalProps {
  /** The tool to edit. Without it, the modal adds a new tool. */
  toolId?: number;
  /** Add mode only: closes the modal. Edit mode routes back to the list. */
  onClose?: () => void;
  /** Add mode only: runs with the new tool's id once it is saved. */
  onCreated?: (toolId: number) => void;
}

function addValues(): OpenAPIPluginFormValues {
  return {
    name: "",
    description: "",
    definition: "",
    enabled: true,
    auth: newOpenApiAuthValues(),
  };
}

/**
 * The one modal for an OpenAPI plugin, for both add and edit, backed by one
 * form. Add mode opens on Schema: Continue checks the schema and unlocks
 * Authentication, where Add Action creates the tool. Edit mode saves every
 * changed tab with one Save.
 */
export default function OpenAPIPluginModal({
  toolId,
  onClose,
  onCreated,
}: OpenAPIPluginModalProps) {
  const isAdd = toolId === undefined;
  const t = useTranslations("actions");
  const { mutate } = useSWRConfig();
  const defaultChat = useDefaultAssistantConfiguration();
  const router = useRouter();
  const searchParams = useSearchParams();
  const {
    openApiTools,
    isLoading,
    error: loadError,
    mutateOpenApiTools,
    refreshOpenApiTools,
  } = useOpenApiTools();
  const tool = isAdd
    ? undefined
    : openApiTools?.find((candidate) => candidate.id === toolId);
  const oauthConfigId = tool?.oauth_config_id ?? null;
  const oauthConfig = useSWR<OAuthConfig, Error>(
    oauthConfigId !== null ? SWR_KEYS.adminOAuthConfig(oauthConfigId) : null,
    errorHandlingFetcher,
    { revalidateOnFocus: false }
  );
  // Both add and edit open on the schema, the plugin's source of truth.
  const initialTab: Tab = "schema";
  const [tab, setTab] = useState<Tab>(initialTab);
  const [visited, setVisited] = useState(() => new Set<Tab>([initialTab]));
  // Kept across submits, so a retry after a failed auth save reuses them.
  const savedId = useRef<number | null>(null);
  const pendingOAuthConfigId = useRef<number | null>(null);
  const checkedSchema = useRef<CheckedOpenApiSchema | null>(null);
  const baseline = useRef<OpenAPIPluginFormValues | null>(null);
  const consumedConfigure = useRef(new Set<number>());
  const active = useRef(true);
  const canEdit = isAdd || can(tool, "edit");
  const canAuthenticate = isAdd || can(tool, "authenticate");
  const canToggle = isAdd || can(tool, "toggle");
  const authSchema = useOpenApiAuthSchema(oauthConfigId !== null);
  const ready =
    isAdd ||
    (tool !== undefined &&
      (oauthConfigId === null ||
        oauthConfig.data !== undefined ||
        oauthConfig.error !== undefined));

  const validationSchema = useMemo(
    () =>
      Yup.object({
        name: Yup.string(),
        description: Yup.string(),
        definition: Yup.string().required(
          t("addOpenApiModal.definition.required")
        ),
        auth: authSchema,
      }),
    [authSchema, t]
  );

  const initialValues = useMemo<OpenAPIPluginFormValues>(
    () =>
      !tool || !ready
        ? addValues()
        : {
            // The schema holds the real name and description; the fields
            // hold only the stored overrides.
            name: tool.name_override ?? "",
            description: tool.description_override ?? "",
            definition: tool.definition
              ? JSON.stringify(tool.definition, null, 2)
              : "",
            enabled: tool.enabled,
            auth: savedOpenApiAuthValues(tool, oauthConfig.data ?? null),
          },
    // The form takes its values once per key, so later refreshes of the
    // same tool do not matter here.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tool?.id, oauthConfigId, ready, oauthConfig.data]
  );

  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);

  function showTab(value: Tab) {
    setTab(value);
    setVisited((current) => new Set([...current, value]));
  }

  useEffect(() => {
    if (
      !tool ||
      searchParams.get("configure") !== "authentication" ||
      consumedConfigure.current.has(tool.id)
    )
      return;
    consumedConfigure.current.add(tool.id);
    const next = new URLSearchParams(searchParams.toString());
    next.delete("configure");
    router.replace(
      withPluginSearchParams(
        pluginDetailHref({ kind: "openapi", id: tool.id }),
        next
      ),
      { scroll: false }
    );
    if (can(tool, "authenticate")) showTab("authentication");
  }, [tool, searchParams, router]);

  function close() {
    if (isAdd) onClose?.();
    else router.replace("/admin/plugins", { scroll: false });
  }

  async function create(values: OpenAPIPluginFormValues) {
    const schema = checkedSchema.current;
    if (!schema) throw new Error(t("addOpenApiModal.definition.invalidJson"));
    if (defaultChat.canEdit && (!defaultChat.data || defaultChat.error))
      throw new Error(t("addOpenApiModal.editConfigsButton.disabledTooltip"));
    // Overrides; empty ones fall back to the schema's.
    const name = values.name.trim();
    const description = values.description.trim();
    // A retry after a failed authentication save updates the saved tool.
    const existing =
      savedId.current === null
        ? null
        : (await refreshOpenApiTools())?.find(
            (candidate) => candidate.id === savedId.current
          );
    if (savedId.current !== null && !existing)
      throw new Error(t("addOpenApiModal.editConfigsButton.disabledTooltip"));
    const response = existing
      ? await updateCustomTool(existing.id, {
          name,
          description,
          definition: schema.definition,
          oauth_config_id: existing.oauth_config_id ?? null,
        })
      : await createCustomTool({
          name,
          description,
          definition: schema.definition,
          custom_headers: [],
          passthrough_auth: false,
        });
    if (response.error || !response.data)
      throw new Error(
        response.error ?? t("addOpenApiModal.toasts.createFailed")
      );
    savedId.current = response.data.id;
    const created = (await refreshOpenApiTools())?.find(
      (candidate) => candidate.id === savedId.current
    );
    if (!created)
      throw new Error(t("addOpenApiModal.editConfigsButton.disabledTooltip"));
    if (
      values.auth.authMethod !== "none" ||
      created.oauth_config_id ||
      created.passthrough_auth ||
      created.custom_headers?.length
    ) {
      if (!can(created, "authenticate"))
        throw new Error(t("addOpenApiModal.editConfigsButton.disabledTooltip"));
      await saveOpenApiAuthentication({
        tool: created,
        values: values.auth,
        pendingOAuthConfigId: pendingOAuthConfigId.current,
        onOAuthConfigCreated: (id) => {
          pendingOAuthConfigId.current = id;
        },
      });
      if (values.auth.authMethod === "oauth")
        pendingOAuthConfigId.current = null;
      await refreshOpenApiTools();
    }
    if (!values.enabled) {
      await updateToolStatus(created.id, false);
      await refreshOpenApiTools();
    } else if (defaultChat.canEdit) {
      await defaultChat.updateTools([created.id], true);
      await refreshOpenApiTools();
    }
    await refreshMemberPluginCaches(mutate);
    if (active.current) onCreated?.(created.id);
  }

  async function save(values: OpenAPIPluginFormValues): Promise<boolean> {
    const base = baseline.current;
    if (!base) return false;
    const metaChanged =
      canEdit &&
      (values.name !== base.name || values.description !== base.description);
    const schemaChanged = canEdit && values.definition !== base.definition;
    const authChanged = canAuthenticate && !isEqual(values.auth, base.auth);
    const enabledChanged = canToggle && values.enabled !== base.enabled;
    if (!metaChanged && !schemaChanged && !authChanged && !enabledChanged)
      return false;

    const fresh: ToolSnapshot | undefined = (await refreshOpenApiTools())?.find(
      (candidate) => candidate.id === toolId
    );
    if (!fresh) throw new Error(t("addOpenApiModal.toasts.updateFailed"));

    if (metaChanged || schemaChanged) {
      if (!can(fresh, "edit"))
        throw new Error(t("addOpenApiModal.toasts.updateFailed"));
      const schema = schemaChanged ? checkedSchema.current : null;
      if (schemaChanged && !schema)
        throw new Error(t("addOpenApiModal.definition.invalidJson"));
      const payload: Parameters<typeof updateCustomTool>[1] = {
        oauth_config_id: fresh.oauth_config_id ?? null,
        // Overrides; empty ones fall back to the schema's.
        name: values.name.trim(),
        description: values.description.trim(),
      };
      if (schema) payload.definition = schema.definition;
      const response = await updateCustomTool(fresh.id, payload);
      if (response.error || !response.data)
        throw new Error(
          response.error ?? t("addOpenApiModal.toasts.updateFailed")
        );
    }

    if (authChanged) {
      if (!can(fresh, "authenticate"))
        throw new Error(t("addOpenApiModal.editConfigsButton.disabledTooltip"));
      // Another session linked a different OAuth configuration meanwhile.
      const currentOAuthConfigId = fresh.oauth_config_id ?? null;
      if (
        currentOAuthConfigId !== oauthConfigId &&
        currentOAuthConfigId !== pendingOAuthConfigId.current
      )
        throw new Error(t("openApiPage.toasts.authSaveFailed"));
      await saveOpenApiAuthentication({
        tool: fresh,
        values: values.auth,
        pendingOAuthConfigId: pendingOAuthConfigId.current,
        onOAuthConfigCreated: (id) => {
          pendingOAuthConfigId.current = id;
        },
      });
      if (values.auth.authMethod === "oauth")
        pendingOAuthConfigId.current = null;
    }

    if (enabledChanged) {
      if (!can(fresh, "toggle"))
        throw new Error(t("addOpenApiModal.toasts.updateFailed"));
      await updateToolStatus(fresh.id, values.enabled);
      // Turning a plugin on also offers it in the default Chat.
      if (values.enabled && defaultChat.canEdit)
        await defaultChat.updateTools([fresh.id], true);
      await refreshMemberPluginCaches(mutate);
    }

    await mutateOpenApiTools();
    return true;
  }

  async function submit(
    values: OpenAPIPluginFormValues,
    { setStatus }: FormikHelpers<OpenAPIPluginFormValues>
  ) {
    setStatus(undefined);
    try {
      if (isAdd) {
        await create(values);
        return;
      }
      if ((await save(values)) && active.current) close();
    } catch (cause) {
      const message =
        cause instanceof Error && cause.message
          ? cause.message
          : t(
              isAdd
                ? "addOpenApiModal.toasts.createFailed"
                : "addOpenApiModal.toasts.updateFailed"
            );
      if (active.current) setStatus(message);
      toast.error(message);
    }
  }

  return (
    <Formik<OpenAPIPluginFormValues>
      // A new OAuth configuration or a loaded tool starts a fresh form.
      key={isAdd ? "add" : `${tool?.id}:${oauthConfigId}:${ready}`}
      initialValues={initialValues}
      validationSchema={validationSchema}
      validateOnMount
      onSubmit={submit}
    >
      <OpenAPIPluginForm
        isAdd={isAdd}
        tool={tool}
        // A missing tool or failed load is not loading; it shows its error.
        loading={!isAdd && (tool ? !ready : isLoading)}
        loadFailed={!isAdd && !tool && !isLoading}
        loadError={loadError !== undefined}
        onRetry={() => void mutateOpenApiTools()}
        canEdit={canEdit}
        canAuthenticate={canAuthenticate}
        canToggle={canToggle}
        oauthConfigId={oauthConfigId}
        oauthConfigError={oauthConfig.error !== undefined}
        tab={tab}
        visited={visited}
        onShowTab={showTab}
        onClose={close}
        checkedSchema={checkedSchema}
        baseline={baseline}
      />
    </Formik>
  );
}

interface OpenAPIPluginFormProps {
  isAdd: boolean;
  tool: ToolSnapshot | undefined;
  loading: boolean;
  loadFailed: boolean;
  loadError: boolean;
  onRetry: () => void;
  canEdit: boolean;
  canAuthenticate: boolean;
  canToggle: boolean;
  oauthConfigId: number | null;
  oauthConfigError: boolean;
  tab: Tab;
  visited: Set<Tab>;
  onShowTab: (tab: Tab) => void;
  onClose: () => void;
  /** Receives the checked schema just before a submit. */
  checkedSchema: MutableRefObject<CheckedOpenApiSchema | null>;
  /** Receives the form's starting values, to find what changed. */
  baseline: MutableRefObject<OpenAPIPluginFormValues | null>;
}

function OpenAPIPluginForm({
  isAdd,
  tool,
  loading,
  loadFailed,
  loadError,
  onRetry,
  canEdit,
  canAuthenticate,
  canToggle,
  oauthConfigId,
  oauthConfigError,
  tab,
  visited,
  onShowTab,
  onClose,
  checkedSchema,
  baseline,
}: OpenAPIPluginFormProps) {
  const t = useTranslations("actions");
  const {
    values,
    initialValues,
    dirty,
    isValid,
    status,
    isSubmitting,
    setFieldTouched,
    validateForm,
    submitForm,
  } = useFormikContext<OpenAPIPluginFormValues>();
  const schema = useOpenApiSchemaCheck(
    values.definition,
    t("addOpenApiModal.definition.invalidJson")
  );
  const busy = isSubmitting || schema.checking;

  useEffect(() => {
    baseline.current = initialValues;
  }, [baseline, initialValues]);

  function selectTab(value: string) {
    if (
      !busy &&
      (value === "server" || value === "schema" || value === "authentication")
    )
      onShowTab(value);
  }

  function close() {
    if (!busy) onClose();
  }

  async function primaryAction() {
    if (isAdd && tab === "schema") {
      void setFieldTouched("definition", true, false);
      if (await schema.check()) onShowTab("authentication");
      return;
    }
    if (isAdd || values.definition !== initialValues.definition) {
      const checked = await schema.check();
      if (!checked) {
        void setFieldTouched("definition", true, false);
        onShowTab("schema");
        return;
      }
      checkedSchema.current = checked;
    }
    const errors = await validateForm();
    await submitForm();
    if (errors.definition) onShowTab("schema");
    else if (errors.auth) onShowTab("authentication");
    else if (errors.name) onShowTab("server");
  }

  const authDescription = t(
    tool?.oauth_config_id
      ? "openApiAuthModal.authMethod.oauth.label"
      : tool?.passthrough_auth
        ? "openApiAuthModal.authMethod.ptOauth.label"
        : tool?.custom_headers?.length
          ? "openApiAuthModal.authMethod.customHeader.label"
          : "openApiAuthModal.authMethod.none.label"
  );

  // The schema's own name and description hint at the defaults.
  const schemaInfo = (schema.checked?.definition ?? tool?.definition)?.info;
  const schemaTitle: string | undefined = schemaInfo?.title;
  const schemaDescription: string | undefined = schemaInfo?.description;

  // Adding: the other tabs wait for a schema that passes the check.
  const schemaLocked = isAdd && !schema.checked;
  const schemaLockedTooltip = schemaLocked
    ? t("plugins.openapi.schemaRequiredTooltip")
    : undefined;

  const addOnSchema = isAdd && tab === "schema";
  // The label stays fixed; the button's spinner shows work in progress.
  const primaryLabel = t(
    addOnSchema
      ? "mcpSetup.continue"
      : isAdd
        ? "addOpenApiModal.submitButton.addLabel"
        : "addOpenApiModal.submitButton.saveLabel"
  );
  const primaryDisabled =
    busy ||
    (addOnSchema
      ? !values.definition.trim()
      : !isValid || (isAdd ? !schema.checked : !dirty));

  return (
    <Modal open onOpenChange={(next) => !next && close()}>
      <PluginModalContent>
        <Modal.Header
          title={
            isAdd
              ? t("addOpenApiModal.addHeader.title")
              : tool
                ? markdown(
                    t("addOpenApiModal.editHeader.title", { name: tool.name })
                  )
                : t("plugins.openapi.detailsTitle")
          }
          icon={PLUGIN_KIND_ICONS.openapi}
          description={t(
            isAdd
              ? "addOpenApiModal.addHeader.description"
              : "addOpenApiModal.editHeader.description"
          )}
          onClose={close}
        />
        <Modal.Body alignItems="stretch" padding={2} gap={0}>
          {loading ? (
            <IconLoader />
          ) : loadFailed ? (
            <InputPadder>
              <div className="flex flex-col items-start gap-4">
                <Content
                  sizePreset="section"
                  variant="section"
                  title={t(
                    loadError
                      ? "plugins.openapi.loadFailed"
                      : "plugins.openapi.notFound"
                  )}
                  description={t("plugins.openapi.unavailable")}
                />
                {loadError && (
                  <Button prominence="secondary" onClick={onRetry}>
                    {t("mcpDetail.retry")}
                  </Button>
                )}
              </div>
            </InputPadder>
          ) : (
            <Tabs
              value={tab}
              onValueChange={selectTab}
              variant="contained"
              gap={0}
            >
              <InputPadder>
                <Tabs.List>
                  <Tabs.Trigger
                    value="server"
                    disabled={busy || schemaLocked}
                    tooltip={schemaLockedTooltip}
                  >
                    {t("plugins.openapi.tabs.details")}
                  </Tabs.Trigger>
                  <Tabs.Trigger value="schema" disabled={busy}>
                    {t("plugins.openapi.tabs.schema")}
                  </Tabs.Trigger>
                  <Tabs.Trigger
                    value="authentication"
                    disabled={busy || schemaLocked}
                    tooltip={schemaLockedTooltip}
                  >
                    {t("mcpDetail.authentication")}
                  </Tabs.Trigger>
                </Tabs.List>
              </InputPadder>

              {typeof status === "string" && (
                <InputPadder>
                  <Text as="p" color="status-error-05">
                    {status}
                  </Text>
                </InputPadder>
              )}

              <Tabs.Content
                value="server"
                keepMounted
                hidden={tab !== "server"}
              >
                {(isAdd || tool) &&
                  (canEdit || canToggle ? (
                    <div className="flex flex-col">
                      {canEdit && (
                        <>
                          <InputPadder>
                            <InputVertical
                              title={t("plugins.openapi.displayNameTitle")}
                              subDescription={markdown(
                                t("plugins.openapi.displayNameDescription")
                              )}
                              withLabel="name"
                              suffix="optional"
                            >
                              <InputTypeInField
                                name="name"
                                placeholder={schemaTitle}
                                variant={busy ? "disabled" : "primary"}
                              />
                            </InputVertical>
                          </InputPadder>
                          <InputPadder>
                            <InputVertical
                              title={t("addMcpModal.description.title")}
                              subDescription={markdown(
                                t("plugins.openapi.descriptionDescription")
                              )}
                              withLabel="description"
                              suffix="optional"
                            >
                              <InputTextAreaField
                                name="description"
                                placeholder={
                                  schemaDescription ||
                                  t("plugins.openapi.descriptionPlaceholder")
                                }
                                variant={busy ? "disabled" : "primary"}
                                rows={3}
                              />
                            </InputVertical>
                          </InputPadder>
                        </>
                      )}
                      {canToggle && (
                        <>
                          {canEdit && (
                            <Divider
                              paddingParallel={2}
                              paddingPerpendicular={2}
                            />
                          )}
                          <InputPadder>
                            <InputHorizontal
                              withLabel="enabled"
                              title={t(
                                "plugins.openapi.workspaceEnabled.title"
                              )}
                              description={t(
                                "plugins.openapi.workspaceEnabled.description"
                              )}
                            >
                              <InputSwitchField
                                name="enabled"
                                disabled={busy}
                              />
                            </InputHorizontal>
                          </InputPadder>
                        </>
                      )}
                    </div>
                  ) : (
                    tool && (
                      <InputPadder>
                        <Content
                          sizePreset="main-ui"
                          variant="section"
                          title={tool.name}
                          description={
                            tool.description || t("plugins.openapi.readOnly")
                          }
                        />
                      </InputPadder>
                    )
                  ))}
              </Tabs.Content>

              <Tabs.Content
                value="schema"
                keepMounted
                hidden={tab !== "schema"}
              >
                {visited.has("schema") &&
                  (canEdit ? (
                    <OpenAPISchemaFields schema={schema} disabled={busy} />
                  ) : (
                    tool && (
                      <div className="flex flex-col">
                        <InputPadder>
                          <InputTextArea
                            value={JSON.stringify(tool.definition, null, 2)}
                            variant="disabled"
                            rows={12}
                            aria-label={t("plugins.openapi.tabs.schema")}
                          />
                        </InputPadder>
                        <InputPadder>
                          <OpenAPIEndpointList
                            methods={extractMethodSpecsFromDefinition(
                              tool.definition
                            )}
                          />
                        </InputPadder>
                      </div>
                    )
                  ))}
              </Tabs.Content>

              <Tabs.Content
                value="authentication"
                keepMounted
                hidden={tab !== "authentication"}
              >
                {visited.has("authentication") &&
                  (canAuthenticate ? (
                    <OpenAPIAuthFields
                      oauthConfigId={oauthConfigId}
                      oauthConfigError={oauthConfigError}
                      disabled={busy}
                    />
                  ) : (
                    <InputPadder>
                      <Content
                        sizePreset="main-ui"
                        variant="section"
                        title={t("mcpDetail.authentication")}
                        description={authDescription}
                      />
                    </InputPadder>
                  ))}
              </Tabs.Content>
            </Tabs>
          )}
        </Modal.Body>
        {(canEdit || canAuthenticate || canToggle) &&
          !loading &&
          !loadFailed && (
            <Modal.Footer padding={4}>
              <div className="ms-auto flex items-center gap-2">
                <Button prominence="secondary" disabled={busy} onClick={close}>
                  {t("addOpenApiModal.cancelButton.label")}
                </Button>
                <Button
                  icon={busy ? IconLoader : undefined}
                  disabled={primaryDisabled}
                  onClick={() => void primaryAction()}
                >
                  {primaryLabel}
                </Button>
              </div>
            </Modal.Footer>
          )}
      </PluginModalContent>
    </Modal>
  );
}
