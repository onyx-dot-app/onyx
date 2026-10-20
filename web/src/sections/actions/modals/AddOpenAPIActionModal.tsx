"use client";

import { markdown } from "@opal/utils";
import type { RichStr } from "@opal/types";
import { useTranslations } from "next-intl";
import {
  Button,
  CopyButton,
  Divider,
  InputTextArea,
  InputTypeIn,
  Modal,
  Tooltip,
  Text,
} from "@opal/components";
import { InputVertical, toast } from "@opal/layouts";
import InputTextAreaField from "@/refresh-components/form/InputTextAreaField";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import PluginAvailabilitySwitch from "@/sections/plugins/PluginAvailabilitySwitch";
import { Hoverable } from "@opal/core";
import type { ToolSnapshot } from "@/lib/tools/types";
import { can } from "@/lib/permissions/resource-actions";
import { validateToolDefinition, type createCustomTool } from "@/lib/tools/svc";
import debounce from "lodash/debounce";
import { DOCS_ADMINS_PATH } from "@/lib/constants";
import { Formik, Form, useFormikContext, type FormikHelpers } from "formik";
import * as Yup from "yup";
import { SvgBracketCurly } from "@opal/icons";
import MCPFormDirtyObserver from "@/sections/actions/modals/MCPFormDirtyObserver";

export type OpenAPIConfigurationValues = Partial<
  Pick<ToolSnapshot, "name" | "description" | "enabled">
> & { definition?: NonNullable<ToolSnapshot["definition"]> };

interface SharedFormProps {
  footerTarget?: HTMLElement | null;
  active?: boolean;
  onBusyChange?: (busy: boolean) => void;
  onDirtyChange?: (dirty: boolean) => void;
  initialDefinition?: ToolSnapshot["definition"];
  initialDescription?: string;
  initialEnabled?: boolean;
  title?: string | RichStr;
  onClose?: () => void;
}

type AddOpenAPIActionModalProps = SharedFormProps &
  (
    | {
        presentation: "inline";
        existingTool: ToolSnapshot;
        onSaveConfiguration: (
          values: OpenAPIConfigurationValues
        ) => Promise<void>;
        onConfigureAuthentication?: never;
      }
    | {
        presentation: "content";
        existingTool?: never;
        onSaveConfiguration?: never;
        onConfigureAuthentication: (
          draft: Parameters<typeof createCustomTool>[0]
        ) => void;
      }
  );

interface OpenAPIActionFormValues {
  name: string;
  description: string;
  enabled: boolean;
  definition: string;
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
  presentation: "inline" | "content";
  footerTarget?: HTMLElement | null;
  active: boolean;
  onBusyChange?: (busy: boolean) => void;
  onDirtyChange?: (dirty: boolean) => void;
  handleClose: () => void;
  existingTool: ToolSnapshot | null;
  title?: string | RichStr;
}

function FormContent({
  presentation,
  footerTarget,
  active,
  onBusyChange,
  onDirtyChange,
  handleClose,
  existingTool,
  title,
}: FormContentProps) {
  const t = useTranslations("actions");
  const fields = useTranslations("agents.editor.general");
  const canEdit = !existingTool || can(existingTool, "edit");
  const {
    values,
    errors,
    setFieldValue,
    setFieldError,
    dirty,
    isSubmitting,
    submitForm,
  } = useFormikContext<OpenAPIActionFormValues>();

  const validationRequest = useRef(0);
  const [checking, setChecking] = useState(false);
  useEffect(() => {
    onBusyChange?.(isSubmitting || checking);
    return () => onBusyChange?.(false);
  }, [isSubmitting, checking, onBusyChange]);
  const editableSchema = useMemo(() => {
    try {
      const parsed: unknown = parseJsonWithTrailingCommas(values.definition);
      if (
        typeof parsed !== "object" ||
        parsed === null ||
        Array.isArray(parsed) ||
        !("info" in parsed)
      )
        return null;
      const info = parsed.info;
      if (typeof info !== "object" || info === null || Array.isArray(info))
        return null;
      return { ...parsed, info };
    } catch {
      return null;
    }
  }, [values.definition]);
  const agentDescription =
    editableSchema &&
    "description" in editableSchema.info &&
    typeof editableSchema.info.description === "string"
      ? editableSchema.info.description
      : "";

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
          setFieldError("definition", response.error);
          return false;
        } else {
          setFieldError("definition", "");
          return true;
        }
      } catch {
        if (request !== validationRequest.current) return false;
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
    if (!values.definition.trim()) {
      setFieldError("definition", "");
    } else {
      debouncedValidateDefinition(values.definition, setFieldError);
    }

    return () => {
      debouncedValidateDefinition.cancel();
      validationRequest.current += 1;
    };
  }, [values.definition, debouncedValidateDefinition, setFieldError]);

  const inlineSave = (
    <Button
      disabled={
        isSubmitting ||
        checking ||
        !dirty ||
        (isEditMode && !values.name.trim()) ||
        (existingTool !== null && !canEdit && !can(existingTool, "toggle"))
      }
      type="button"
      onClick={() => void submitForm()}
    >
      {primaryButtonLabel}
    </Button>
  );

  const definitionField = (
    <div className="w-full">
      <InputVertical
        withLabel="definition"
        title={t("addOpenApiModal.definition.title")}
        description={markdown(
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
                      disabled={checking || isSubmitting || !canEdit}
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
                variant={
                  checking || isSubmitting || !canEdit ? "disabled" : undefined
                }
                rows={8}
                placeholder={t("addOpenApiModal.definition.placeholder")}
              />
            </div>
          </div>
        </Hoverable.Root>
      </InputVertical>
      {errors.definition && (
        <Text font="secondary-body" color="status-error-05">
          {errors.definition}
        </Text>
      )}
    </div>
  );

  return (
    <Form className="contents">
      {onDirtyChange && <MCPFormDirtyObserver onDirtyChange={onDirtyChange} />}
      {presentation !== "inline" && (
        <Modal.Header
          padding={4}
          title={title ?? modalTitle}
          onClose={handleClose}
        />
      )}

      <Modal.Body
        twoTone={false}
        padding={presentation === "inline" ? 0 : 6}
        gap={4}
        alignItems="stretch"
      >
        {isEditMode && (
          <InputVertical title={fields("name.title")} withLabel="plugin-name">
            <InputTypeIn
              id="plugin-name"
              value={values.name}
              onChange={(event) => setFieldValue("name", event.target.value)}
              variant={isSubmitting || !canEdit ? "disabled" : "primary"}
            />
          </InputVertical>
        )}
        {!isEditMode && definitionField}
        <InputVertical
          title={t("addOpenApiModal.humanDescription.title")}
          suffix="optional"
          description={t("addOpenApiModal.humanDescription.hint")}
          withLabel="plugin-description"
        >
          <InputTextArea
            id="plugin-description"
            value={values.description}
            onChange={(event) =>
              setFieldValue("description", event.target.value)
            }
            variant={
              checking || isSubmitting || !canEdit ? "disabled" : "primary"
            }
            rows={3}
          />
        </InputVertical>
        <InputVertical
          title={t("addOpenApiModal.agentDescription.title")}
          description={t("addOpenApiModal.agentDescription.hint")}
          withLabel="plugin-agent-description"
        >
          <Tooltip
            tooltip={
              !editableSchema
                ? t("addOpenApiModal.agentDescription.disabled")
                : undefined
            }
            side="top"
          >
            <div className="w-full">
              <InputTextArea
                id="plugin-agent-description"
                value={agentDescription}
                onChange={(event) => {
                  if (!editableSchema) return;
                  setFieldValue(
                    "definition",
                    JSON.stringify(
                      {
                        ...editableSchema,
                        info: {
                          ...editableSchema.info,
                          description: event.target.value,
                        },
                      },
                      null,
                      2
                    )
                  );
                }}
                variant={
                  checking || isSubmitting || !canEdit || !editableSchema
                    ? "disabled"
                    : "primary"
                }
                rows={3}
              />
            </div>
          </Tooltip>
        </InputVertical>
        {isEditMode && definitionField}
        {(!existingTool || can(existingTool, "toggle")) && (
          <>
            <Divider paddingParallel={0} />
            <PluginAvailabilitySwitch
              surface="workspace"
              enabled={values.enabled}
              onChange={(enabled) => setFieldValue("enabled", enabled)}
              disabled={isSubmitting}
            />
          </>
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
            <Button
              type="button"
              disabled={!values.definition.trim() || checking}
              onClick={async () => {
                setChecking(true);
                debouncedValidateDefinition.cancel();
                const validation = validateDefinition(
                  values.definition,
                  setFieldError
                );
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
          </div>
        </Modal.Footer>
      )}
    </Form>
  );
}

export default function AddOpenAPIActionModal({
  onSaveConfiguration,
  presentation,
  footerTarget,
  active = true,
  onBusyChange,
  onDirtyChange,
  existingTool,
  onClose,
  title,
  initialDefinition,
  initialDescription,
  initialEnabled,
  onConfigureAuthentication,
}: AddOpenAPIActionModalProps) {
  const t = useTranslations("actions");

  const validationSchema = Yup.object().shape({
    definition: Yup.string().required(t("addOpenApiModal.definition.required")),
  });

  const initialValues: OpenAPIActionFormValues = useMemo(
    () => ({
      name: existingTool?.name ?? "",
      description: existingTool?.description ?? initialDescription ?? "",
      enabled: existingTool?.enabled ?? initialEnabled ?? true,
      definition:
        existingTool?.definition || initialDefinition
          ? JSON.stringify(
              existingTool?.definition ?? initialDefinition,
              null,
              2
            )
          : "",
    }),
    [existingTool, initialDefinition, initialDescription, initialEnabled]
  );

  const configurationBaseline = useRef(initialValues);

  const handleSubmit = async (
    values: OpenAPIActionFormValues,
    { resetForm }: FormikHelpers<OpenAPIActionFormValues>
  ) => {
    if (onSaveConfiguration) {
      if (!values.name.trim()) return;
      try {
        const changes: OpenAPIConfigurationValues = {};
        if (values.name !== configurationBaseline.current.name)
          changes.name = values.name.trim();
        if (values.description !== configurationBaseline.current.description)
          changes.description = values.description.trim();
        if (values.enabled !== configurationBaseline.current.enabled)
          changes.enabled = values.enabled;
        if (values.definition !== configurationBaseline.current.definition) {
          const definition = parseJsonWithTrailingCommas(values.definition);
          const validation = await validateToolDefinition({ definition });
          if (validation.error) throw new Error(validation.error);
          changes.definition = definition;
        }
        await onSaveConfiguration(changes);
        configurationBaseline.current = values;
        resetForm({ values });
      } catch (error) {
        toast.error(
          error instanceof Error
            ? error.message
            : t("addOpenApiModal.toasts.updateFailed")
        );
      }
      return;
    }
    try {
      const definition = parseJsonWithTrailingCommas(values.definition);
      onConfigureAuthentication({
        name: definition.info.title,
        description: values.description.trim(),
        definition,
        custom_headers: [],
        passthrough_auth: false,
        enabled: values.enabled,
      });
    } catch {
      toast.error(t("addOpenApiModal.toasts.invalidJson"));
    }
  };

  return (
    <Formik
      initialValues={initialValues}
      validationSchema={validationSchema}
      onSubmit={handleSubmit}
    >
      <FormContent
        presentation={presentation}
        footerTarget={footerTarget}
        active={active}
        onBusyChange={onBusyChange}
        onDirtyChange={onDirtyChange}
        handleClose={() => onClose?.()}
        existingTool={existingTool ?? null}
        title={title}
      />
    </Formik>
  );
}
