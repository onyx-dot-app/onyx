"use client";

import { cn, markdown } from "@opal/utils";
import type { RichStr } from "@opal/types";
import { useTranslations } from "next-intl";
import { Card, Divider, Modal } from "@opal/components";
import { Text } from "@opal/components";
import { Content, ContentAction, InputVertical, toast } from "@opal/layouts";
import InputTextAreaField from "@/refresh-components/form/InputTextAreaField";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { CopyButton } from "@opal/components";
import { Button } from "@opal/components";
import PluginModalContent from "@/sections/plugins/PluginModalContent";
import { OpenAPIMethodPath } from "@/sections/plugins/OpenAPIEndpointList";
import { Hoverable } from "@opal/core";
import { MethodSpec, ToolSnapshot } from "@/lib/tools/types";
import { can } from "@/lib/permissions/resource-actions";
import {
  validateToolDefinition,
  createCustomTool,
  updateCustomTool,
} from "@/lib/plugins/openapi/svc";
import debounce from "lodash/debounce";
import { DOCS_ADMINS_PATH } from "@/lib/constants";
import { useModal } from "@opal/components";
import { Formik, Form, useFormikContext, type FormikHelpers } from "formik";
import * as Yup from "yup";
import { SvgActions, SvgArrowRightDot, SvgBracketCurly } from "@opal/icons";
import { getActionIcon } from "@/lib/tools/utils";
import { EmptyMessageCard } from "@opal/components";
import useOpenApiTools from "@/hooks/useOpenApiTools";
import MCPFormDirtyObserver from "@/views/admin/PluginsPage/components/mcp/MCPFormDirtyObserver";
import { PLUGIN_KIND_ICONS } from "@/lib/plugins/constants";

interface AddOpenAPIActionModalProps {
  onViewTools?: () => void;
  presentation?: "modal" | "inline";
  footerTarget?: HTMLElement | null;
  active?: boolean;
  onBusyChange?: (busy: boolean) => void;
  onDirtyChange?: (dirty: boolean) => void;
  initialDefinition?: ToolSnapshot["definition"];
  onConfigureAuthentication?: (
    draft: Parameters<typeof createCustomTool>[0]
  ) => void;
  /** Runs when the schema text changes, so a checked draft can go stale. */
  onDefinitionChange?: () => void;
  skipOverlay?: boolean;
  onSuccess?: (tool: ToolSnapshot) => Promise<void> | void;
  onUpdate?: (tool: ToolSnapshot) => Promise<void> | void;
  title?: string | RichStr;
  existingTool?: ToolSnapshot | null;
  onClose?: () => void;
}

interface OpenAPIActionFormValues {
  definition: string;
}

interface CheckedDefinition {
  rawDefinition: string;
  definition: NonNullable<ToolSnapshot["definition"]>;
  methods: MethodSpec[];
}

function parseJsonWithTrailingCommas(jsonString: string) {
  const cleanedJsonString = jsonString.replace(
    /"(?:\\.|[^"\\])*"|,\s*(?=[}\]])|\b(?:True|False|None)\b/g,
    (token: string) => {
      switch (token) {
        case "True":
          return "true";
        case "False":
          return "false";
        case "None":
          return "null";
        default:
          return token.startsWith(",") ? "" : token;
      }
    }
  );
  return JSON.parse(cleanedJsonString);
}

interface FormContentProps {
  onViewTools?: () => void;
  presentation: "modal" | "inline";
  footerTarget?: HTMLElement | null;
  active: boolean;
  onBusyChange?: (busy: boolean) => void;
  onDirtyChange?: (dirty: boolean) => void;
  configureAuthentication?: boolean;
  onDefinitionChange?: () => void;
  handleClose: () => void;
  existingTool: ToolSnapshot | null;
  title?: string | RichStr;
}

function FormContent({
  onViewTools,
  presentation,
  footerTarget,
  active,
  onBusyChange,
  onDirtyChange,
  handleClose,
  existingTool,
  title,
  configureAuthentication = false,
  onDefinitionChange,
}: FormContentProps) {
  const t = useTranslations("actions");
  const {
    values,
    setFieldValue,
    setFieldError,
    dirty,
    isSubmitting,
    submitForm,
  } = useFormikContext<OpenAPIActionFormValues>();

  const [checkedDefinition, setCheckedDefinition] =
    useState<CheckedDefinition | null>(null);
  const validationRequest = useRef(0);
  const [checking, setChecking] = useState(false);
  useEffect(() => {
    onBusyChange?.(isSubmitting || checking);
    return () => onBusyChange?.(false);
  }, [isSubmitting, checking, onBusyChange]);
  const currentDefinition =
    checkedDefinition?.rawDefinition === values.definition
      ? checkedDefinition
      : null;
  const methodSpecs = currentDefinition?.methods;
  const name = currentDefinition?.definition.info?.title;
  const description = currentDefinition?.definition.info?.description;
  const url = currentDefinition?.definition.servers?.[0]?.url;
  const PluginIcon = getActionIcon(url ?? "", name ?? "");

  const isEditMode = Boolean(existingTool);

  const handleFormat = useCallback(() => {
    if (!values.definition.trim()) {
      return;
    }

    try {
      const formatted = JSON.stringify(
        parseJsonWithTrailingCommas(values.definition),
        null,
        2
      );
      setFieldValue("definition", formatted);
      setFieldError("definition", "");
    } catch {
      setFieldError("definition", t("addOpenApiModal.definition.invalidJson"));
    }
  }, [values.definition, setFieldValue, setFieldError, t]);

  const validateDefinition = useCallback(
    async (
      rawDefinition: string,
      setFieldError: (field: string, message: string) => void
    ) => {
      const request = ++validationRequest.current;
      if (!rawDefinition.trim()) {
        setCheckedDefinition(null);
        setFieldError("definition", "");
        return false;
      }

      try {
        const parsedDefinition = parseJsonWithTrailingCommas(rawDefinition);
        const response = await validateToolDefinition({
          definition: parsedDefinition,
        });

        if (request !== validationRequest.current) return false;

        if (response.error) {
          setCheckedDefinition(null);
          setFieldError("definition", response.error);
          return false;
        } else {
          setCheckedDefinition({
            rawDefinition,
            definition: parsedDefinition,
            methods: response.data ?? [],
          });
          setFieldError("definition", "");
          return true;
        }
      } catch {
        if (request !== validationRequest.current) return false;
        setCheckedDefinition(null);
        setFieldError(
          "definition",
          t("addOpenApiModal.definition.invalidJson")
        );
        return false;
      }
    },
    [t]
  );

  const debouncedValidateDefinition = useMemo(
    () => debounce(validateDefinition, 300),
    [validateDefinition]
  );

  const modalTitle = isEditMode
    ? t("addOpenApiModal.editHeader.title")
    : t("addOpenApiModal.addHeader.title");
  const primaryButtonLabel = isSubmitting
    ? isEditMode
      ? t("addOpenApiModal.submitButton.savingLabel")
      : t("addOpenApiModal.submitButton.addingLabel")
    : isEditMode
      ? t("addOpenApiModal.submitButton.saveLabel")
      : t("addOpenApiModal.submitButton.addLabel");

  useEffect(() => {
    onDefinitionChange?.();
    if (!values.definition.trim()) {
      setCheckedDefinition(null);
      setFieldError("definition", "");
    } else {
      debouncedValidateDefinition(values.definition, setFieldError);
    }

    return () => {
      debouncedValidateDefinition.cancel();
      validationRequest.current += 1;
    };
  }, [
    values.definition,
    debouncedValidateDefinition,
    setFieldError,
    onDefinitionChange,
  ]);

  // Add mode checks the schema, then hands the draft on for authentication.
  const continueButton = (
    <Button
      type="button"
      disabled={!values.definition.trim() || checking || isSubmitting}
      onClick={async () => {
        setChecking(true);
        debouncedValidateDefinition.cancel();
        const validation = validateDefinition(values.definition, setFieldError);
        const request = validationRequest.current;
        try {
          if (await validation) await submitForm();
        } finally {
          if (request === validationRequest.current) setChecking(false);
        }
      }}
    >
      {checking ? t("mcpSetup.checking") : t("mcpSetup.continue")}
    </Button>
  );

  const inlineSave = !isEditMode ? (
    continueButton
  ) : (
    <Button
      disabled={
        isSubmitting ||
        checking ||
        !dirty ||
        (existingTool !== null && !can(existingTool, "edit"))
      }
      type="button"
      onClick={() => void submitForm()}
    >
      {primaryButtonLabel}
    </Button>
  );

  return (
    <Form className="contents">
      {onDirtyChange && <MCPFormDirtyObserver onDirtyChange={onDirtyChange} />}
      {presentation === "modal" && (
        <Modal.Header
          padding={4}
          icon={PLUGIN_KIND_ICONS.openapi}
          title={title ?? modalTitle}
          description={t("addOpenApiModal.addHeader.description")}
          onClose={handleClose}
        />
      )}

      <Modal.Body
        padding={presentation === "inline" ? 0 : 6}
        gap={4}
        alignItems="stretch"
      >
        <div className="w-full">
          <InputVertical
            withLabel="definition"
            title={t("addOpenApiModal.definition.title")}
            subDescription={markdown(
              t("addOpenApiModal.definition.subDescription", {
                docsUrl: `${DOCS_ADMINS_PATH}/actions/openapi`,
              })
            )}
          >
            <Hoverable.Root group="definitionField" width="full">
              <div className="relative w-full">
                {values.definition.trim() && (
                  <div className="absolute z-100000 top-2 end-2 bg-background-tint-00">
                    <Hoverable.Item
                      group="definitionField"
                      variant="appear-on-hover"
                    >
                      <div className="flex">
                        <CopyButton
                          prominence="tertiary"
                          size="sm"
                          getCopyText={() => values.definition}
                          tooltip={t("addOpenApiModal.copyButton.tooltip")}
                        />
                        <Button
                          prominence="tertiary"
                          size="sm"
                          icon={SvgBracketCurly}
                          disabled={checking || isSubmitting}
                          aria-label={t("addOpenApiModal.formatButton.tooltip")}
                          tooltip={t("addOpenApiModal.formatButton.tooltip")}
                          onClick={handleFormat}
                        />
                      </div>
                    </Hoverable.Item>
                  </div>
                )}
                <div className="font-main-ui-mono">
                  <InputTextAreaField
                    name="definition"
                    variant={checking || isSubmitting ? "disabled" : undefined}
                    rows={8}
                    placeholder={t("addOpenApiModal.definition.placeholder")}
                  />
                </div>
              </div>
            </Hoverable.Root>
          </InputVertical>
        </div>
        {presentation === "inline" && isEditMode ? (
          currentDefinition && (
            <div className="flex items-center justify-between gap-3">
              <Text font="secondary-body" color="text-03">
                {t("plugins.openapi.schemaPreview.detected", {
                  count: currentDefinition.methods.length,
                })}
              </Text>
              {onViewTools && (
                <Button
                  size="sm"
                  prominence="tertiary"
                  disabled={dirty || checking || isSubmitting}
                  tooltip={
                    dirty
                      ? t("plugins.openapi.schemaPreview.saveToUpdate")
                      : undefined
                  }
                  onClick={onViewTools}
                >
                  {t("plugins.openapi.schemaPreview.viewTools")}
                </Button>
              )}
            </div>
          )
        ) : (
          <div
            hidden={!isEditMode && !methodSpecs?.length}
            className={cn(
              "w-full min-w-0 flex-col gap-4",
              !isEditMode && !methodSpecs?.length ? "hidden" : "flex"
            )}
          >
            {methodSpecs && methodSpecs.length > 0 ? (
              <>
                {name && (
                  <Content
                    sizePreset="main-content"
                    variant="section"
                    icon={PluginIcon}
                    title={name}
                    description={description}
                  />
                )}
                {url && (
                  <Content
                    sizePreset="main-ui"
                    variant="section"
                    title={url}
                    description={t("addOpenApiModal.preview.urlDescription")}
                  />
                )}
                <Divider paddingParallel={0} />
                <div className="flex flex-col gap-2">
                  {methodSpecs.map((method) => (
                    <Card
                      key={`${method.method}-${method.path}-${method.name}`}
                      padding={2}
                      border="solid"
                    >
                      <ContentAction
                        sizePreset="main-ui"
                        variant="section"
                        padding={0}
                        rightChildren={<OpenAPIMethodPath method={method} />}
                        icon={SvgArrowRightDot}
                        title={method.name}
                        description={
                          method.summary ||
                          t("addOpenApiModal.method.noSummary")
                        }
                      />
                    </Card>
                  ))}
                </div>
              </>
            ) : (
              <EmptyMessageCard
                sizePreset="main-ui"
                title={t("addOpenApiModal.empty.title")}
                icon={SvgActions}
                description={t("addOpenApiModal.empty.description")}
              />
            )}
          </div>
        )}
      </Modal.Body>

      {presentation === "inline" ? (
        active &&
        (footerTarget ? createPortal(inlineSave, footerTarget) : inlineSave)
      ) : (
        <Modal.Footer padding={6}>
          <div className="ms-auto flex items-center gap-2">
            <Button
              disabled={isSubmitting || checking}
              prominence="secondary"
              type="button"
              onClick={handleClose}
            >
              {t("addOpenApiModal.cancelButton.label")}
            </Button>
            {!isEditMode ? (
              continueButton
            ) : (
              <Button
                disabled={
                  isSubmitting ||
                  (!dirty && !configureAuthentication) ||
                  (existingTool !== null && !can(existingTool, "edit"))
                }
                type="submit"
              >
                {configureAuthentication
                  ? t("mcpSetup.continue")
                  : primaryButtonLabel}
              </Button>
            )}
          </div>
        </Modal.Footer>
      )}
    </Form>
  );
}

function OpenAPIActionEditor({
  onViewTools,
  presentation = "modal",
  footerTarget,
  active = true,
  onBusyChange,
  onDirtyChange,
  skipOverlay = false,
  onSuccess,
  onUpdate,
  existingTool = null,
  onClose,
  title,
  initialDefinition,
  onConfigureAuthentication,
  onDefinitionChange,
  modalOpen = false,
  onModalOpenChange,
}: AddOpenAPIActionModalProps & {
  modalOpen?: boolean;
  onModalOpenChange?: (open: boolean) => void;
}) {
  const t = useTranslations("actions");
  const { refreshOpenApiTools } = useOpenApiTools();

  const validationSchema = Yup.object().shape({
    definition: Yup.string().required(t("addOpenApiModal.definition.required")),
  });

  const handleModalClose = useCallback(
    (open: boolean) => {
      onModalOpenChange?.(open);
      if (!open) {
        onClose?.();
      }
    },
    [onModalOpenChange, onClose]
  );

  const handleClose = useCallback(() => {
    handleModalClose(false);
  }, [handleModalClose]);

  const initialValues: OpenAPIActionFormValues = useMemo(
    () => ({
      definition:
        existingTool?.definition || initialDefinition
          ? JSON.stringify(
              existingTool?.definition ?? initialDefinition,
              null,
              2
            )
          : "",
    }),
    [existingTool, initialDefinition]
  );

  const handleSubmit = async (
    values: OpenAPIActionFormValues,
    { resetForm }: FormikHelpers<OpenAPIActionFormValues>
  ) => {
    if (existingTool && !can(existingTool, "edit")) return;
    let parsedDefinition;
    try {
      parsedDefinition = parseJsonWithTrailingCommas(values.definition);
    } catch (error) {
      console.error("Error parsing OpenAPI definition:", error);
      toast.error(t("addOpenApiModal.toasts.invalidJson"));
      return;
    }

    const derivedName = parsedDefinition?.info?.title;
    const derivedDescription = parsedDefinition?.info?.description;
    if (!existingTool && onConfigureAuthentication) {
      onConfigureAuthentication({
        name: derivedName,
        description: derivedDescription || undefined,
        definition: parsedDefinition,
        custom_headers: [],
        passthrough_auth: false,
      });
      return;
    }

    if (existingTool) {
      try {
        const tools = await refreshOpenApiTools();
        const freshTool = tools?.find((tool) => tool.id === existingTool.id);
        if (!freshTool || !can(freshTool, "edit")) {
          toast.error(t("addOpenApiModal.toasts.updateFailed"));
          return;
        }
        const updatePayload: Parameters<typeof updateCustomTool>[1] = {
          definition: parsedDefinition,
          oauth_config_id: freshTool.oauth_config_id ?? null,
        };

        if (derivedName) {
          updatePayload.name = derivedName;
        }

        if (derivedDescription) {
          updatePayload.description = derivedDescription;
        }

        const response = await updateCustomTool(existingTool.id, updatePayload);

        if (response.error) {
          toast.error(response.error);
        } else {
          toast.success(t("addOpenApiModal.toasts.actionUpdated"));
          if (response.data && onUpdate) {
            await onUpdate(response.data);
          }
          if (presentation === "inline") resetForm({ values });
          else handleClose();
        }
      } catch (error) {
        console.error("Error updating OpenAPI action:", error);
        toast.error(t("addOpenApiModal.toasts.updateFailed"));
      }
      return;
    }

    try {
      const response = await createCustomTool({
        name: derivedName,
        description: derivedDescription || undefined,
        definition: parsedDefinition,
        custom_headers: [],
        passthrough_auth: false,
      });

      if (response.error) {
        toast.error(response.error);
      } else {
        toast.success(t("addOpenApiModal.toasts.actionCreated"));
        if (response.data && onSuccess) {
          await onSuccess(response.data);
        }
        handleClose();
      }
    } catch (error) {
      console.error("Error creating OpenAPI action:", error);
      toast.error(t("addOpenApiModal.toasts.createFailed"));
    }
  };

  const form = (
    <Formik
      initialValues={initialValues}
      validationSchema={validationSchema}
      onSubmit={handleSubmit}
    >
      <FormContent
        onViewTools={onViewTools}
        presentation={presentation}
        footerTarget={footerTarget}
        active={active}
        onBusyChange={onBusyChange}
        onDirtyChange={onDirtyChange}
        handleClose={handleClose}
        existingTool={existingTool}
        title={title}
        configureAuthentication={!!onConfigureAuthentication}
        onDefinitionChange={onDefinitionChange}
      />
    </Formik>
  );
  if (presentation === "inline") return form;
  return (
    <Modal open={modalOpen} onOpenChange={handleModalClose}>
      <PluginModalContent skipOverlay={skipOverlay}>{form}</PluginModalContent>
    </Modal>
  );
}

function ModalOpenAPIActionEditor(props: AddOpenAPIActionModalProps) {
  const { isOpen, toggle } = useModal();
  return (
    <OpenAPIActionEditor
      {...props}
      modalOpen={isOpen}
      onModalOpenChange={toggle}
    />
  );
}

export default function AddOpenAPIActionModal(
  props: AddOpenAPIActionModalProps
) {
  return props.presentation === "inline" ? (
    <OpenAPIActionEditor {...props} />
  ) : (
    <ModalOpenAPIActionEditor {...props} />
  );
}
