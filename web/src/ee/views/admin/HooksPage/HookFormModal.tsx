"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Formik, Form, useFormikContext } from "formik";
import * as Yup from "yup";
import { Button, LinkButton, Text } from "@opal/components";
import {
  SvgCheckCircle,
  SvgShareWebhook,
  SvgLoader,
  SvgRevert,
} from "@opal/icons";
import { BasicModalFooter, Modal } from "@opal/components";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import PasswordInputTypeInField from "@/refresh-components/form/PasswordInputTypeInField";
import { Section } from "@/layouts/general-layouts";
import { Content, ContentAction, InputVertical, toast } from "@opal/layouts";
import {
  createHook,
  updateHook,
  HookAuthError,
  HookTimeoutError,
  HookConnectError,
} from "@/ee/views/admin/HooksPage/svc";
import type {
  HookFailStrategy,
  HookFormState,
  HookPointMeta,
  HookResponse,
  HookUpdateRequest,
} from "@/ee/views/admin/HooksPage/interfaces";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface HookFormModalProps {
  onOpenChange: (open: boolean) => void;
  /** When provided, the modal is in edit mode for this hook. */
  hook?: HookResponse;
  /** When provided (create mode), the hook point is pre-selected and locked. */
  spec?: HookPointMeta;
  onSuccess: (hook: HookResponse) => void;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const MAX_TIMEOUT_SECONDS = 600;

type HooksTranslate = ReturnType<typeof useTranslations<"admin.hooks">>;

function buildInitialValues(
  hook: HookResponse | undefined,
  spec: HookPointMeta | undefined
): HookFormState {
  if (hook) {
    return {
      name: hook.name,
      endpoint_url: hook.endpoint_url ?? "",
      api_key: "",
      fail_strategy: hook.fail_strategy,
      timeout_seconds: String(hook.timeout_seconds),
    };
  }
  return {
    name: "",
    endpoint_url: "",
    api_key: "",
    fail_strategy: spec?.default_fail_strategy ?? "hard",
    timeout_seconds: spec ? String(spec.default_timeout_seconds) : "30",
  };
}

function buildValidationSchema(isEdit: boolean, t: HooksTranslate) {
  return Yup.object().shape({
    name: Yup.string().trim().required(t("form.validation.nameRequired")),
    endpoint_url: Yup.string()
      .trim()
      .required(t("form.validation.endpointRequired")),
    api_key: isEdit
      ? Yup.string()
      : Yup.string().trim().required(t("form.validation.apiKeyRequired")),
    timeout_seconds: Yup.string()
      .required(t("form.validation.timeoutRequired"))
      .test(
        "valid-timeout",
        t("form.validation.timeoutRange", { max: MAX_TIMEOUT_SECONDS }),
        (val) => {
          const num = parseFloat(val ?? "");
          return !isNaN(num) && num > 0 && num <= MAX_TIMEOUT_SECONDS;
        }
      ),
  });
}

// ---------------------------------------------------------------------------
// Timeout field (needs access to spec for revert button)
// ---------------------------------------------------------------------------

interface TimeoutFieldProps {
  spec: HookPointMeta | undefined;
}

function TimeoutField({ spec }: TimeoutFieldProps) {
  const t = useTranslations("admin.hooks");
  const { values, setFieldValue, isSubmitting } =
    useFormikContext<HookFormState>();

  return (
    <InputVertical
      withLabel="timeout_seconds"
      title={t("form.timeout.title")}
      suffix={t("form.timeout.suffix")}
      subDescription={t("form.timeout.description", {
        max: MAX_TIMEOUT_SECONDS,
      })}
    >
      <div className="[&_input]:!font-main-ui-mono [&_input::placeholder]:!font-main-ui-mono [&_input]:[appearance:textfield]! [&_input::-webkit-outer-spin-button]:appearance-none! [&_input::-webkit-inner-spin-button]:appearance-none! w-full">
        <InputTypeInField
          name="timeout_seconds"
          type="number"
          placeholder={spec ? String(spec.default_timeout_seconds) : undefined}
          variant={isSubmitting ? "disabled" : undefined}
          rightChildren={
            spec?.default_timeout_seconds !== undefined &&
            values.timeout_seconds !== String(spec.default_timeout_seconds) ? (
              <Button
                prominence="tertiary"
                size="xs"
                icon={SvgRevert}
                tooltip={t("form.timeout.revert.tooltip")}
                onClick={() =>
                  setFieldValue(
                    "timeout_seconds",
                    String(spec.default_timeout_seconds)
                  )
                }
                disabled={isSubmitting}
              />
            ) : undefined
          }
        />
      </div>
    </InputVertical>
  );
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function HookFormModal({
  onOpenChange,
  hook,
  spec,
  onSuccess,
}: HookFormModalProps) {
  const t = useTranslations("admin.hooks");
  const isEdit = !!hook;
  const [isConnected, setIsConnected] = useState(false);
  const [apiKeyCleared, setApiKeyCleared] = useState(false);

  const initialValues = buildInitialValues(hook, spec);
  const validationSchema = buildValidationSchema(isEdit, t);

  function handleClose() {
    onOpenChange(false);
  }

  const hookPointDisplayName =
    spec?.display_name ?? spec?.hook_point ?? hook?.hook_point ?? "";
  const hookPointDescription = spec?.description;
  const docsUrl = spec?.docs_url;

  return (
    <Modal open onOpenChange={(open) => !open && handleClose()}>
      <Modal.Content width="md" height="fit">
        <Formik
          initialValues={initialValues}
          validationSchema={validationSchema}
          validateOnMount
          onSubmit={async (values, helpers) => {
            try {
              let result: HookResponse;
              if (isEdit && hook) {
                const req: HookUpdateRequest = {};
                if (values.name !== hook.name) req.name = values.name;
                if (values.endpoint_url !== (hook.endpoint_url ?? ""))
                  req.endpoint_url = values.endpoint_url;
                if (values.fail_strategy !== hook.fail_strategy)
                  req.fail_strategy = values.fail_strategy;
                const timeoutNum = parseFloat(values.timeout_seconds);
                if (timeoutNum !== hook.timeout_seconds)
                  req.timeout_seconds = timeoutNum;
                if (values.api_key.trim().length > 0) {
                  req.api_key = values.api_key;
                } else if (apiKeyCleared) {
                  req.api_key = null;
                }
                if (Object.keys(req).length === 0) {
                  handleClose();
                  return;
                }
                result = await updateHook(hook.id, req);
              } else {
                if (!spec) {
                  toast.error(t("form.toasts.noHookPoint.message"));
                  return;
                }
                result = await createHook({
                  name: values.name,
                  hook_point: spec.hook_point,
                  endpoint_url: values.endpoint_url,
                  ...(values.api_key ? { api_key: values.api_key } : {}),
                  fail_strategy: values.fail_strategy,
                  timeout_seconds: parseFloat(values.timeout_seconds),
                });
              }
              toast.success(
                isEdit
                  ? t("form.toasts.updated.message")
                  : t("form.toasts.created.message")
              );
              onSuccess(result);
              if (!isEdit) {
                setIsConnected(true);
                await new Promise((resolve) => setTimeout(resolve, 500));
              }
              handleClose();
            } catch (err) {
              if (err instanceof HookAuthError) {
                helpers.setFieldError(
                  "api_key",
                  t("form.errors.invalidApiKey")
                );
              } else if (err instanceof HookTimeoutError) {
                helpers.setFieldError(
                  "timeout_seconds",
                  t("form.errors.timeout")
                );
              } else if (err instanceof HookConnectError) {
                helpers.setFieldError(
                  "endpoint_url",
                  err.message || t("form.errors.connect")
                );
              } else {
                toast.error(
                  err instanceof Error ? err.message : t("form.errors.generic")
                );
              }
            } finally {
              helpers.setSubmitting(false);
            }
          }}
        >
          {({ values, setFieldValue, isSubmitting, isValid, dirty }) => {
            const failStrategyDescription =
              values.fail_strategy === "soft"
                ? t("form.softStrategy.description")
                : spec?.fail_hard_description;

            return (
              <Form className="w-full overflow-visible">
                <Modal.Header
                  icon={SvgShareWebhook}
                  title={
                    isEdit
                      ? t("form.editHeader.title")
                      : t("form.createHeader.title")
                  }
                  description={
                    isEdit ? undefined : t("form.createHeader.description")
                  }
                  onClose={handleClose}
                />

                <Modal.Body>
                  {/* Hook point section header */}
                  <ContentAction
                    sizePreset="main-ui"
                    variant="section"
                    padding={0}
                    title={hookPointDisplayName}
                    description={hookPointDescription}
                    rightChildren={
                      <div className="flex flex-col items-end gap-1">
                        <Content
                          sizePreset="secondary"
                          variant="body"
                          icon={SvgShareWebhook}
                          title={t("form.hookPoint.label")}
                          color="muted"
                          width="fit"
                        />
                        {docsUrl && (
                          <LinkButton href={docsUrl} target="_blank">
                            {t("docsLink.label")}
                          </LinkButton>
                        )}
                      </div>
                    }
                  />

                  <InputVertical withLabel="name" title={t("form.name.title")}>
                    <div className="[&_input::placeholder]:!font-main-ui-muted w-full">
                      <InputTypeInField
                        name="name"
                        placeholder={t("form.name.placeholder")}
                        variant={isSubmitting ? "disabled" : undefined}
                      />
                    </div>
                  </InputVertical>

                  <InputVertical
                    withLabel="fail_strategy"
                    title={t("form.failStrategy.title")}
                    subDescription={failStrategyDescription}
                  >
                    <InputSelect
                      value={values.fail_strategy}
                      onValueChange={(v) =>
                        setFieldValue("fail_strategy", v as HookFailStrategy)
                      }
                      disabled={isSubmitting}
                    >
                      <InputSelect.Trigger
                        placeholder={t("form.failStrategy.placeholder")}
                      />
                      <InputSelect.Content>
                        <InputSelect.Item value="soft">
                          {t("form.failStrategy.soft.label")}
                          {spec?.default_fail_strategy === "soft" && (
                            <>
                              {" "}
                              <Text color="text-03">
                                {t("form.failStrategy.default.label")}
                              </Text>
                            </>
                          )}
                        </InputSelect.Item>
                        <InputSelect.Item value="hard">
                          {t("form.failStrategy.hard.label")}
                          {spec?.default_fail_strategy === "hard" && (
                            <>
                              {" "}
                              <Text color="text-03">
                                {t("form.failStrategy.default.label")}
                              </Text>
                            </>
                          )}
                        </InputSelect.Item>
                      </InputSelect.Content>
                    </InputSelect>
                  </InputVertical>

                  <TimeoutField spec={spec} />

                  <InputVertical
                    withLabel="endpoint_url"
                    title={t("form.endpoint.title")}
                    subDescription={t("form.endpoint.description")}
                  >
                    <div className="[&_input::placeholder]:!font-main-ui-muted w-full">
                      <InputTypeInField
                        name="endpoint_url"
                        placeholder="https://your-api-endpoint.com"
                        variant={isSubmitting ? "disabled" : undefined}
                      />
                    </div>
                  </InputVertical>

                  <InputVertical
                    withLabel="api_key"
                    title={t("form.apiKey.title")}
                    subDescription={t("form.apiKey.description")}
                  >
                    <PasswordInputTypeInField
                      name="api_key"
                      placeholder={
                        isEdit
                          ? (hook?.api_key_masked ??
                            t("form.apiKey.keepCurrent.placeholder"))
                          : undefined
                      }
                      disabled={isSubmitting}
                      onChange={(e) => {
                        if (isEdit && hook?.api_key_masked) {
                          setApiKeyCleared(e.target.value === "");
                        }
                      }}
                    />
                  </InputVertical>

                  {!isEdit && (isSubmitting || isConnected) && (
                    <Section
                      flexDirection="row"
                      alignItems="center"
                      justifyContent="start"
                      height="fit"
                      gap={4}
                      className="px-0.5"
                    >
                      <div className="p-0.5 shrink-0">
                        {isConnected ? (
                          <SvgCheckCircle
                            size={16}
                            className="text-status-success-05"
                          />
                        ) : (
                          <SvgLoader
                            size={16}
                            className="animate-spin text-text-03"
                          />
                        )}
                      </div>
                      <Text font="secondary-body" color="text-03">
                        {isConnected
                          ? t("form.connectionValid.label")
                          : t("form.verifying.label")}
                      </Text>
                    </Section>
                  )}
                </Modal.Body>

                <Modal.Footer>
                  <BasicModalFooter
                    cancel={
                      <Button
                        disabled={isSubmitting}
                        prominence="secondary"
                        onClick={handleClose}
                      >
                        {t("modals.cancel.label")}
                      </Button>
                    }
                    submit={
                      <Button
                        disabled={
                          isSubmitting ||
                          !isValid ||
                          (!dirty && !apiKeyCleared && isEdit)
                        }
                        type="submit"
                        icon={
                          isSubmitting && !isEdit
                            ? () => (
                                <SvgLoader size={16} className="animate-spin" />
                              )
                            : undefined
                        }
                      >
                        {isEdit
                          ? t("form.save.label")
                          : t("connectButton.label")}
                      </Button>
                    }
                  />
                </Modal.Footer>
              </Form>
            );
          }}
        </Formik>
      </Modal.Content>
    </Modal>
  );
}
