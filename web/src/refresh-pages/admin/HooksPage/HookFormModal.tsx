"use client";

import { useState } from "react";
import { Button } from "@opal/components";
import { Disabled } from "@opal/core";
import { SvgCheckCircle, SvgHookNodes, SvgLoader } from "@opal/icons";
import Modal, { BasicModalFooter } from "@/refresh-components/Modal";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import PasswordInputTypeIn from "@/refresh-components/inputs/PasswordInputTypeIn";
import Text from "@/refresh-components/texts/Text";
import { toast } from "@/hooks/useToast";
import { cn } from "@/lib/utils";
import { createHook, updateHook } from "@/refresh-pages/admin/HooksPage/svc";
import type {
  HookFailStrategy,
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

interface FormState {
  name: string;
  endpoint_url: string;
  api_key: string;
  fail_strategy: HookFailStrategy;
  timeout_seconds: string;
}

function buildInitialState(
  hook: HookResponse | undefined,
  spec: HookPointMeta | undefined
): FormState {
  if (hook) {
    return {
      name: hook.name,
      endpoint_url: hook.endpoint_url ?? "",
      api_key: hook.api_key_masked ?? "",
      fail_strategy: hook.fail_strategy,
      timeout_seconds: String(hook.timeout_seconds),
    };
  }
  return {
    name: "",
    endpoint_url: "",
    api_key: "",
    fail_strategy: spec?.default_fail_strategy ?? "hard",
    timeout_seconds: spec ? String(spec.default_timeout_seconds) : "5",
  };
}

const SOFT_DESCRIPTION =
  "If the endpoint returns an error, Onyx logs it and continues the pipeline as normal, ignoring the hook result.";

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

interface FieldProps {
  label: React.ReactNode;
  description?: string;
  children: React.ReactNode;
}

function Field({ label, description, children }: FieldProps) {
  return (
    <div className="flex flex-col gap-1 w-full">
      <span className="font-main-ui-action text-text-04 px-[0.125rem]">
        {label}
      </span>
      {children}
      {description && (
        <Text secondaryBody text03>
          {description}
        </Text>
      )}
    </div>
  );
}

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
  const [form, setForm] = useState<FormState>(() =>
    buildInitialState(hook, spec)
  );
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isConnected, setIsConnected] = useState(false);

  function handleOpenChange(next: boolean) {
    if (!next) {
      setTimeout(() => {
        setForm(buildInitialState(hook, spec));
        setIsSubmitting(false);
        setIsConnected(false);
      }, 200);
    }
    onOpenChange(next);
  }

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  const timeoutNum = parseFloat(form.timeout_seconds);
  const isValid =
    form.name.trim().length > 0 &&
    form.endpoint_url.trim().length > 0 &&
    !isNaN(timeoutNum) &&
    timeoutNum > 0;

  const hasChanges =
    isEdit && hook
      ? form.name !== hook.name ||
        form.endpoint_url !== (hook.endpoint_url ?? "") ||
        form.fail_strategy !== hook.fail_strategy ||
        timeoutNum !== hook.timeout_seconds ||
        form.api_key !== (hook.api_key_masked ?? "")
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
        const maskedPlaceholder = hook.api_key_masked ?? "";
        if (form.api_key !== maskedPlaceholder) {
          req.api_key = form.api_key || null;
        }
        if (Object.keys(req).length === 0) {
          setIsSubmitting(false);
          handleOpenChange(false);
          return;
        }
        result = await updateHook(hook.id, req);
      } else {
        const hookPoint = spec!.hook_point;
        result = await createHook({
          name: form.name,
          hook_point: hookPoint,
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
      toast.error(err instanceof Error ? err.message : "Something went wrong.");
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
          <div className="flex flex-row items-start justify-between gap-1 w-full">
            <div className="flex flex-col flex-1 min-w-0">
              <span className="font-main-ui-action text-text-04 px-[0.125rem]">
                {hookPointDisplayName}
              </span>
              {hookPointDescription && (
                <span className="font-secondary-body text-text-03 px-[0.125rem]">
                  {hookPointDescription}
                </span>
              )}
            </div>
            <div className="flex flex-col items-end shrink-0 gap-1">
              <div className="flex items-center gap-1">
                <SvgHookNodes
                  style={{ width: "1rem", height: "1rem" }}
                  className="text-text-03 shrink-0 p-0.5"
                />
                <span className="font-secondary-body text-text-03">
                  Hook Point
                </span>
              </div>
              {docsUrl && (
                <a
                  href={docsUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="font-secondary-body text-text-03 underline"
                >
                  Documentation
                </a>
              )}
            </div>
          </div>

          <Field label="Display Name">
            <div className="[&_input::placeholder]:!font-main-ui-muted w-full">
              <InputTypeIn
                value={form.name}
                onChange={(e) => set("name", e.target.value)}
                placeholder="Name your extension at this hook point"
                variant={isSubmitting ? "disabled" : undefined}
              />
            </div>
          </Field>

          <Field label="Fail Strategy" description={failStrategyDescription}>
            <InputSelect
              value={form.fail_strategy}
              onValueChange={(v) => set("fail_strategy", v as HookFailStrategy)}
              disabled={isSubmitting}
            >
              <InputSelect.Trigger placeholder="Select strategy" />
              <InputSelect.Content>
                <InputSelect.Item value="soft">
                  Log Error and Continue
                  {(spec?.default_fail_strategy ?? "hard") === "soft" && (
                    <>
                      {" "}
                      <span className="text-text-03">(Default)</span>
                    </>
                  )}
                </InputSelect.Item>
                <InputSelect.Item value="hard">
                  Block Pipeline on Failure
                  {(spec?.default_fail_strategy ?? "hard") === "hard" && (
                    <>
                      {" "}
                      <span className="text-text-03">(Default)</span>
                    </>
                  )}
                </InputSelect.Item>
              </InputSelect.Content>
            </InputSelect>
          </Field>

          <Field
            label={
              <>
                Timeout <span className="text-text-03">(seconds)</span>
              </>
            }
            description="Maximum time Onyx will wait for the endpoint to respond before applying the fail strategy."
          >
            <div className="[&_input]:!font-main-ui-mono [&_input::placeholder]:!font-main-ui-mono w-full">
              <InputTypeIn
                type="number"
                value={form.timeout_seconds}
                onChange={(e) => set("timeout_seconds", e.target.value)}
                placeholder={
                  spec ? String(spec.default_timeout_seconds) : undefined
                }
                variant={isSubmitting ? "disabled" : undefined}
              />
            </div>
          </Field>

          <Field
            label="External API Endpoint URL"
            description="Only connect to servers you trust. You are responsible for actions taken and data shared with this connection."
          >
            <div className="[&_input::placeholder]:!font-main-ui-muted w-full">
              <InputTypeIn
                value={form.endpoint_url}
                onChange={(e) => set("endpoint_url", e.target.value)}
                placeholder="https://your-api-endpoint.com"
                variant={isSubmitting ? "disabled" : undefined}
              />
            </div>
          </Field>

          <Field
            label="API Key"
            description="Onyx will use this key to authenticate with your API endpoint."
          >
            <PasswordInputTypeIn
              value={form.api_key}
              onChange={(e) => set("api_key", e.target.value)}
              placeholder={
                isEdit && hook?.api_key_masked
                  ? "Leave blank to keep current key"
                  : undefined
              }
              disabled={isSubmitting}
            />
          </Field>

          {!isEdit && (isSubmitting || isConnected) && (
            <div className="flex flex-row items-center gap-1 px-0.5 w-full">
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
              <span
                className={cn(
                  "font-secondary-body",
                  isConnected ? "text-status-success-05" : "text-text-03"
                )}
              >
                {isConnected ? "Connection valid." : "Verifying connection…"}
              </span>
            </div>
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
