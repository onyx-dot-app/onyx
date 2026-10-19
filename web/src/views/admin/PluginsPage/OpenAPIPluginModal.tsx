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
  InputTextArea,
  InputTypeIn,
  Modal,
  Tabs,
  Text,
} from "@opal/components";
import { Content, InputPadder, InputVertical, toast } from "@opal/layouts";
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

type Tab = "server" | "schema" | "authentication" | "tools";

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
  const initialTab: Tab = isAdd ? "schema" : "server";
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
        name:
          isAdd || !canEdit
            ? Yup.string()
            : Yup.string().trim().required(t("plugins.openapi.nameRequired")),
        description: Yup.string(),
        definition: Yup.string().required(
          t("addOpenApiModal.definition.required")
        ),
        auth: authSchema,
      }),
    [isAdd, canEdit, authSchema, t]
  );

  const initialValues = useMemo<OpenAPIPluginFormValues>(
    () =>
      !tool || !ready
        ? addValues()
        : {
            name: tool.name,
            description: tool.description,
            definition: tool.definition
              ? JSON.stringify(tool.definition, null, 2)
              : "",
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
    const info = schema.definition.info;
    const name: string = info?.title ?? "";
    const description: string | undefined = info?.description || undefined;
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
    if (defaultChat.canEdit) {
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
    if (!metaChanged && !schemaChanged && !authChanged) return false;

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
      const info = schema?.definition.info;
      const payload: Parameters<typeof updateCustomTool>[1] = {
        oauth_config_id: fresh.oauth_config_id ?? null,
      };
      if (schema) payload.definition = schema.definition;
      // An edited name wins; otherwise a new schema renames the tool.
      const name: string | undefined = metaChanged
        ? values.name.trim()
        : info?.title;
      const description: string | undefined = metaChanged
        ? values.description.trim()
        : info?.description;
      if (name) payload.name = name;
      if (metaChanged || description) payload.description = description;
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

    await mutateOpenApiTools();
    return true;
  }

  async function submit(
    values: OpenAPIPluginFormValues,
    { setStatus, resetForm }: FormikHelpers<OpenAPIPluginFormValues>
  ) {
    setStatus(undefined);
    try {
      if (isAdd) {
        await create(values);
        return;
      }
      if (await save(values)) {
        toast.success(t("addOpenApiModal.toasts.actionUpdated"));
        if (active.current) resetForm({ values });
      }
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
      onSubmit={submit}
    >
      <OpenAPIPluginForm
        isAdd={isAdd}
        tool={tool}
        loading={!isAdd && (!ready || (!tool && isLoading))}
        loadFailed={!isAdd && !tool && !isLoading}
        loadError={loadError !== undefined}
        onRetry={() => void mutateOpenApiTools()}
        canEdit={canEdit}
        canAuthenticate={canAuthenticate}
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
  const fields = useTranslations("agents.editor.general");
  const {
    values,
    initialValues,
    dirty,
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
  const [toolSearch, setToolSearch] = useState("");
  const busy = isSubmitting || schema.checking;

  useEffect(() => {
    baseline.current = initialValues;
  }, [baseline, initialValues]);

  function selectTab(value: string) {
    if (
      !busy &&
      (value === "server" ||
        value === "schema" ||
        value === "authentication" ||
        value === "tools")
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

  const methods = extractMethodSpecsFromDefinition(tool?.definition);
  const filteredMethods = methods.filter((method) =>
    `${method.name} ${method.summary ?? ""} ${method.path}`
      .toLowerCase()
      .includes(toolSearch.trim().toLowerCase())
  );
  const authDescription = t(
    tool?.oauth_config_id
      ? "openApiAuthModal.authMethod.oauth.label"
      : tool?.passthrough_auth
        ? "openApiAuthModal.authMethod.ptOauth.label"
        : tool?.custom_headers?.length
          ? "openApiAuthModal.authMethod.customHeader.label"
          : "openApiAuthModal.authMethod.none.label"
  );

  const addOnSchema = isAdd && tab === "schema";
  const primaryLabel = addOnSchema
    ? t(schema.checking ? "mcpSetup.checking" : "mcpSetup.continue")
    : isAdd
      ? t(
          isSubmitting
            ? "addOpenApiModal.submitButton.addingLabel"
            : "addOpenApiModal.submitButton.addLabel"
        )
      : t(
          isSubmitting
            ? "addOpenApiModal.submitButton.savingLabel"
            : "addOpenApiModal.submitButton.saveLabel"
        );
  const primaryDisabled =
    busy ||
    (addOnSchema
      ? !values.definition.trim()
      : isAdd
        ? !schema.checked
        : !dirty);

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
                  <Tabs.Trigger value="server" disabled={busy || isAdd}>
                    {t("plugins.openapi.detailsTitle")}
                  </Tabs.Trigger>
                  <Tabs.Trigger value="schema" disabled={busy}>
                    {t("plugins.openapi.schemaTitle")}
                  </Tabs.Trigger>
                  <Tabs.Trigger
                    value="authentication"
                    disabled={busy || (isAdd && !schema.checked)}
                  >
                    {t("mcpDetail.authentication")}
                  </Tabs.Trigger>
                  <Tabs.Trigger value="tools" disabled={busy || isAdd}>
                    {t("mcpTools.title")}
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
                {tool &&
                  (canEdit ? (
                    <div className="flex flex-col">
                      <InputPadder>
                        <InputVertical
                          title={fields("name.title")}
                          withLabel="name"
                        >
                          <InputTypeInField
                            name="name"
                            variant={busy ? "disabled" : "primary"}
                          />
                        </InputVertical>
                      </InputPadder>
                      <InputPadder>
                        <InputVertical
                          title={t("addMcpModal.description.title")}
                          withLabel="description"
                        >
                          <InputTextAreaField
                            name="description"
                            variant={busy ? "disabled" : "primary"}
                            rows={3}
                          />
                        </InputVertical>
                      </InputPadder>
                    </div>
                  ) : (
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
                  ))}
              </Tabs.Content>

              <Tabs.Content
                value="schema"
                keepMounted
                hidden={tab !== "schema"}
              >
                {visited.has("schema") &&
                  (canEdit ? (
                    <OpenAPISchemaFields
                      isAdd={isAdd}
                      schema={schema}
                      disabled={busy}
                      onViewTools={isAdd ? undefined : () => onShowTab("tools")}
                    />
                  ) : (
                    tool && (
                      <InputPadder>
                        <InputTextArea
                          value={JSON.stringify(tool.definition, null, 2)}
                          variant="disabled"
                          rows={12}
                          aria-label={t("plugins.openapi.schemaTitle")}
                        />
                      </InputPadder>
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

              <Tabs.Content value="tools">
                <div className="flex flex-col">
                  <InputPadder>
                    <InputTypeIn
                      searchIcon
                      value={toolSearch}
                      onChange={(event) => setToolSearch(event.target.value)}
                      placeholder={t("mcpTools.search")}
                      aria-label={t("mcpTools.search")}
                    />
                  </InputPadder>
                  <InputPadder>
                    {filteredMethods.length ? (
                      <OpenAPIEndpointList methods={filteredMethods} />
                    ) : (
                      <Text as="p" color="text-03">
                        {t(
                          toolSearch.trim()
                            ? "toolsList.empty.searchMessage"
                            : "toolsList.empty.message"
                        )}
                      </Text>
                    )}
                  </InputPadder>
                </div>
              </Tabs.Content>
            </Tabs>
          )}
        </Modal.Body>
        {(canEdit || canAuthenticate) && !loading && !loadFailed && (
          <Modal.Footer padding={4}>
            <div className="ms-auto flex items-center gap-2">
              <Button
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
