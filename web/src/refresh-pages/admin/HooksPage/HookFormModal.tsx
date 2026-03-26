"use client";

import { useState } from "react";
import { Button, Text } from "@opal/components";
import { Disabled } from "@opal/core";
import {
  SvgCheckCircle,
  SvgHookNodes,
  SvgLoader,
  SvgRevert,
} from "@opal/icons";
import Modal, { BasicModalFooter } from "@/refresh-components/Modal";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import PasswordInputTypeIn from "@/refresh-components/inputs/PasswordInputTypeIn";
import { FormField } from "@/refresh-components/form/FormField";
import { Section } from "@/layouts/general-layouts";
import { ContentAction } from "@opal/layouts";
import { toast } from "@/hooks/useToast";
import {
  createHook,
  updateHook,
  HookAuthError,
  HookTimeoutError,
  HookConnectError,
} from "@/refresh-pages/admin/HooksPage/svc";
import type {
  HookFailStrategy,
  HookFormState,
  HookPointMeta,
  HookResponse,
  HookUpdateRequest,
} from "@/refresh-pages/admin/HooksPage/interfaces";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface HookFormModalProps {
  open: boolean;
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

function buildInitialState(
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

const SOFT_DESCRIPTION =
  "If the endpoint returns an error, Onyx logs it and continues the pipeline as normal, ignoring the hook result.";

const MAX_TIMEOUT_SECONDS = 600;

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function HookFormModal({
  open,
  onOpenChange,
  hook,
  spec,
  onSuccess,
}: HookFormModalProps) {
  const isEdit = !!hook;
  const [form, setForm] = useState<HookFormState>(() =>
    buildInitialState(hook, spec)
  );
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isConnected, setIsConnected] = useState(false);
  // Tracks whether the user explicitly cleared the API key field in edit mode.
  // - false + empty field  → key unchanged (omitted from PATCH)
  // - true  + empty field  → key cleared (api_key: null sent to backend)
  // - false + non-empty    → new key provided (new value sent to backend)
  const [apiKeyCleared, setApiKeyCleared] = useState(false);
  const [touched, setTouched] = useState({
    name: false,
    endpoint_url: false,
    api_key: false,
  });
  const [apiKeyServerError, setApiKeyServerError] = useState(false);
  const [endpointServerError, setEndpointServerError] = useState<string | null>(
    null
  );
  const [timeoutServerError, setTimeoutServerError] = useState(false);

  function touch(key: keyof typeof touched) {
    setTouched((prev) => ({ ...prev, [key]: true }));
  }

  function handleOpenChange(next: boolean) {
    if (!next) {
      if (isSubmitting) return;
      setTimeout(() => {
        setForm(buildInitialState(hook, spec));
        setIsConnected(false);
        setApiKeyCleared(false);
        setTouched({ name: false, endpoint_url: false, api_key: false });
        setApiKeyServerError(false);
        setEndpointServerError(null);
        setTimeoutServerError(false);
      }, 200);
    }
    onOpenChange(next);
  }

  function set<K extends keyof HookFormState>(key: K, value: HookFormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  const timeoutNum = parseFloat(form.timeout_seconds);
  const isTimeoutValid =
    !isNaN(timeoutNum) && timeoutNum > 0 && timeoutNum <= MAX_TIMEOUT_SECONDS;
  const isValid =
    form.name.trim().length > 0 &&
    form.endpoint_url.trim().length > 0 &&
    isTimeoutValid &&
    (isEdit || form.api_key.trim().length > 0);

  const nameError = touched.name && !form.name.trim();
  const endpointEmptyError = touched.endpoint_url && !form.endpoint_url.trim();
  const endpointFieldError = endpointEmptyError
    ? "Endpoint URL cannot be empty."
    : endpointServerError ?? undefined;
  const apiKeyEmptyError = !isEdit && touched.api_key && !form.api_key.trim();
  const apiKeyFieldError = apiKeyEmptyError
    ? "API key cannot be empty."
    : apiKeyServerError
      ? "Invalid API key."
      : undefined;

  function handleTimeoutBlur() {
    if (!isTimeoutValid) {
      const fallback = hook?.timeout_seconds ?? spec?.default_timeout_seconds;
      if (fallback !== undefined) {
        set("timeout_seconds", String(fallback));
        if (timeoutServerError) setTimeoutServerError(false);
      }
    }
  }

  const hasChanges =
    isEdit && hook
      ? form.name !== hook.name ||
        form.endpoint_url !== (hook.endpoint_url ?? "") ||
        form.fail_strategy !== hook.fail_strategy ||
        timeoutNum !== hook.timeout_seconds ||
        form.api_key.trim().length > 0 ||
        apiKeyCleared
      : true;

  async function handleSubmit() {
    if (!isValid) return;

    setIsSubmitting(true);
    try {
      let result: HookResponse;
      if (isEdit && hook) {
        const req: HookUpdateRequest = {};
        if (form.name !== hook.name) req.name = form.name;
        if (form.endpoint_url !== (hook.endpoint_url ?? ""))
          req.endpoint_url = form.endpoint_url;
        if (form.fail_strategy !== hook.fail_strategy)
          req.fail_strategy = form.fail_strategy;
        if (timeoutNum !== hook.timeout_seconds)
          req.timeout_seconds = timeoutNum;
        if (form.api_key.trim().length > 0) {
          req.api_key = form.api_key;
        } else if (apiKeyCleared) {
          req.api_key = null;
        }
        if (Object.keys(req).length === 0) {
          setIsSubmitting(false);
          handleOpenChange(false);
          return;
        }
        result = await updateHook(hook.id, req);
      } else {
        if (!spec) {
          toast.error("No hook point specified.");
          setIsSubmitting(false);
          return;
        }
        result = await createHook({
          name: form.name,
          hook_point: spec.hook_point,
          endpoint_url: form.endpoint_url,
          ...(form.api_key ? { api_key: form.api_key } : {}),
          fail_strategy: form.fail_strategy,
          timeout_seconds: timeoutNum,
        });
      }
      toast.success(isEdit ? "Hook updated." : "Hook created.");
      onSuccess(result);
      if (!isEdit) {
        setIsConnected(true);
        await new Promise((resolve) => setTimeout(resolve, 500));
      }
      setIsSubmitting(false);
      handleOpenChange(false);
    } catch (err) {
      if (err instanceof HookAuthError) {
        setApiKeyServerError(true);
      } else if (err instanceof HookTimeoutError) {
        setTimeoutServerError(true);
      } else if (err instanceof HookConnectError) {
        setEndpointServerError(err.message || "Could not connect to endpoint.");
      } else {
        toast.error(
          err instanceof Error ? err.message : "Something went wrong."
        );
      }
      setIsSubmitting(false);
    }
  }

  const hookPointDisplayName =
    spec?.display_name ?? spec?.hook_point ?? hook?.hook_point ?? "";
  const hookPointDescription = spec?.description;
  const docsUrl = spec?.docs_url;

  const failStrategyDescription =
    form.fail_strategy === "soft"
      ? SOFT_DESCRIPTION
      : spec?.fail_hard_description;

  return (
    <Modal open={open} onOpenChange={handleOpenChange}>
      <Modal.Content width="md" height="fit">
        <Modal.Header
          icon={SvgHookNodes}
          title={isEdit ? "Manage Hook Extension" : "Set Up Hook Extension"}
          description={
            isEdit
              ? undefined
              : "Connect an external API endpoint to extend the hook point."
          }
          onClose={() => handleOpenChange(false)}
        />

        <Modal.Body>
          {/* Hook point section header */}
          <ContentAction
            sizePreset="main-ui"
            variant="section"
            paddingVariant="fit"
            title={hookPointDisplayName}
            description={hookPointDescription}
            rightChildren={
              <Section
                flexDirection="column"
                alignItems="end"
                width="fit"
                height="fit"
                gap={0.25}
              >
                <div className="flex items-center gap-1">
                  <SvgHookNodes
                    style={{ width: "1rem", height: "1rem" }}
                    className="text-text-03 shrink-0"
                  />
                  <Text font="secondary-body" color="text-03">
                    Hook Point
                  </Text>
                </div>
                {docsUrl && (
                  <a
                    href={docsUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="underline"
                  >
                    <Text font="secondary-body" color="text-03">
                      Documentation
                    </Text>
                  </a>
                )}
              </Section>
            }
          />

          <FormField className="w-full" state={nameError ? "error" : "idle"}>
            <FormField.Label>Display Name</FormField.Label>
            <FormField.Control>
              <div className="[&_input::placeholder]:!font-main-ui-muted w-full">
                <InputTypeIn
                  value={form.name}
                  onChange={(e) => set("name", e.target.value)}
                  onBlur={() => touch("name")}
                  placeholder="Name your extension at this hook point"
                  variant={
                    isSubmitting ? "disabled" : nameError ? "error" : undefined
                  }
                />
              </div>
            </FormField.Control>
            <FormField.Message
              messages={{ error: "Display name cannot be empty." }}
            />
          </FormField>

          <FormField className="w-full">
            <FormField.Label>Fail Strategy</FormField.Label>
            <FormField.Control>
              <InputSelect
                value={form.fail_strategy}
                onValueChange={(v) =>
                  set("fail_strategy", v as HookFailStrategy)
                }
                disabled={isSubmitting}
              >
                <InputSelect.Trigger placeholder="Select strategy" />
                <InputSelect.Content>
                  <InputSelect.Item value="soft">
                    Log Error and Continue
                    {spec?.default_fail_strategy === "soft" && (
                      <>
                        {" "}
                        <Text color="text-03">(Default)</Text>
                      </>
                    )}
                  </InputSelect.Item>
                  <InputSelect.Item value="hard">
                    Block Pipeline on Failure
                    {spec?.default_fail_strategy === "hard" && (
                      <>
                        {" "}
                        <Text color="text-03">(Default)</Text>
                      </>
                    )}
                  </InputSelect.Item>
                </InputSelect.Content>
              </InputSelect>
            </FormField.Control>
            <FormField.Description>
              {failStrategyDescription}
            </FormField.Description>
          </FormField>

          <FormField
            className="w-full"
            state={timeoutServerError ? "error" : "idle"}
          >
            <FormField.Label>
              Timeout{" "}
              <Text font="main-ui-action" color="text-03">
                (seconds)
              </Text>
            </FormField.Label>
            <FormField.Control>
              <div className="[&_input]:!font-main-ui-mono [&_input::placeholder]:!font-main-ui-mono [&_input]:![appearance:textfield] [&_input::-webkit-outer-spin-button]:!appearance-none [&_input::-webkit-inner-spin-button]:!appearance-none w-full">
                <InputTypeIn
                  type="number"
                  value={form.timeout_seconds}
                  onChange={(e) => {
                    set("timeout_seconds", e.target.value);
                    if (timeoutServerError) setTimeoutServerError(false);
                  }}
                  onBlur={handleTimeoutBlur}
                  placeholder={
                    spec ? String(spec.default_timeout_seconds) : undefined
                  }
                  variant={
                    isSubmitting
                      ? "disabled"
                      : timeoutServerError
                        ? "error"
                        : undefined
                  }
                  showClearButton={false}
                  rightSection={
                    spec?.default_timeout_seconds !== undefined &&
                    form.timeout_seconds !==
                      String(spec.default_timeout_seconds) ? (
                      <Button
                        prominence="tertiary"
                        size="xs"
                        icon={SvgRevert}
                        tooltip="Revert to Default"
                        onClick={() =>
                          set(
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
            </FormField.Control>
            {!timeoutServerError && (
              <FormField.Description>
                Maximum time Onyx will wait for the endpoint to respond before
                applying the fail strategy. Must be greater than 0 and at most{" "}
                {MAX_TIMEOUT_SECONDS} seconds.
              </FormField.Description>
            )}
            <FormField.Message
              messages={{
                error: "Connection timed out. Try increasing the timeout.",
              }}
            />
          </FormField>

          <FormField
            className="w-full"
            state={endpointFieldError ? "error" : "idle"}
          >
            <FormField.Label>External API Endpoint URL</FormField.Label>
            <FormField.Control>
              <div className="[&_input::placeholder]:!font-main-ui-muted w-full">
                <InputTypeIn
                  value={form.endpoint_url}
                  onChange={(e) => {
                    set("endpoint_url", e.target.value);
                    if (endpointServerError) setEndpointServerError(null);
                  }}
                  onBlur={() => touch("endpoint_url")}
                  placeholder="https://your-api-endpoint.com"
                  variant={
                    isSubmitting
                      ? "disabled"
                      : endpointFieldError
                        ? "error"
                        : undefined
                  }
                />
              </div>
            </FormField.Control>
            {!endpointFieldError && (
              <FormField.Description>
                Only connect to servers you trust. You are responsible for
                actions taken and data shared with this connection.
              </FormField.Description>
            )}
            <FormField.Message messages={{ error: endpointFieldError }} />
          </FormField>

          <FormField
            className="w-full"
            state={apiKeyFieldError ? "error" : "idle"}
          >
            <FormField.Label>API Key</FormField.Label>
            <FormField.Control>
              <PasswordInputTypeIn
                value={form.api_key}
                onChange={(e) => {
                  set("api_key", e.target.value);
                  if (apiKeyServerError) setApiKeyServerError(false);
                  if (isEdit) {
                    setApiKeyCleared(
                      e.target.value === "" && !!hook?.api_key_masked
                    );
                  }
                }}
                onBlur={() => touch("api_key")}
                placeholder={
                  isEdit
                    ? hook?.api_key_masked ?? "Leave blank to keep current key"
                    : undefined
                }
                disabled={isSubmitting}
                error={!!apiKeyFieldError}
              />
            </FormField.Control>
            {!apiKeyFieldError && (
              <FormField.Description>
                Onyx will use this key to authenticate with your API endpoint.
              </FormField.Description>
            )}
            <FormField.Message messages={{ error: apiKeyFieldError }} />
          </FormField>

          {!isEdit && (isSubmitting || isConnected) && (
            <Section
              flexDirection="row"
              alignItems="center"
              justifyContent="start"
              height="fit"
              gap={1}
              className="px-0.5"
            >
              <div className="p-0.5 shrink-0">
                {isConnected ? (
                  <SvgCheckCircle
                    size={16}
                    className="text-status-success-05"
                  />
                ) : (
                  <SvgLoader size={16} className="animate-spin text-text-03" />
                )}
              </div>
              <Text font="secondary-body" color="text-03">
                {isConnected ? "Connection valid." : "Verifying connection…"}
              </Text>
            </Section>
          )}
        </Modal.Body>

        <Modal.Footer>
          <BasicModalFooter
            cancel={
              <Disabled disabled={isSubmitting}>
                <Button
                  prominence="secondary"
                  onClick={() => handleOpenChange(false)}
                >
                  Cancel
                </Button>
              </Disabled>
            }
            submit={
              <Disabled disabled={isSubmitting || !isValid || !hasChanges}>
                <Button
                  onClick={handleSubmit}
                  icon={
                    isSubmitting && !isEdit
                      ? () => <SvgLoader size={16} className="animate-spin" />
                      : undefined
                  }
                >
                  {isEdit ? "Save Changes" : "Connect"}
                </Button>
              </Disabled>
            }
          />
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
