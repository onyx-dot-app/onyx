"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { useTranslations } from "next-intl";
import { Button, InputPasswordTypeIn, Modal, Text } from "@opal/components";
import { SvgArrowLeft, SvgKey } from "@opal/icons";
import { FormField } from "@/refresh-components/form/FormField";
import { UnsavedChangesModalContent } from "@/sections/modals/UnsavedChangesModal";
import {
  MCPConnectionStatus,
  type MCPAuthenticationServer,
} from "@/lib/mcp/types";

export interface MCPUserCredentialsModalProps {
  server: MCPAuthenticationServer;
  onClose: () => void;
  onSubmit: (credentials: Record<string, string>) => Promise<void>;
}

interface MCPUserCredentialsContentProps extends MCPUserCredentialsModalProps {
  skipOverlay?: boolean;
  onBack?: () => void;
  onDismissFocus?: () => void;
}

export default function MCPUserCredentialsModal(
  props: MCPUserCredentialsModalProps
) {
  return (
    <Modal open>
      <MCPUserCredentialsContent {...props} />
    </Modal>
  );
}

export function MCPUserCredentialsContent({
  server,
  onClose,
  onSubmit,
  onBack,
  onDismissFocus,
  skipOverlay = false,
}: MCPUserCredentialsContentProps) {
  const t = useTranslations("chat.mcpApiKey");
  const [credentials, setCredentials] = useState<Record<string, string>>(
    server.user_credentials ?? {}
  );
  const closing = useRef(false);
  const initialCredentials = useRef(server.user_credentials ?? {});
  const firstInputRef = useRef<HTMLInputElement>(null);
  const confirmationRef = useRef<HTMLDivElement>(null);
  const [pendingExit, setPendingExit] = useState<"back" | "close" | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const templateFields = server.auth_template?.required_fields ?? [];
  const isTemplate = templateFields.length > 0;
  const fields = isTemplate ? templateFields : ["api_key"];
  const hasRequiredCredentials = fields.every((field) =>
    credentials[field]?.trim()
  );
  const dirty = fields.some(
    (field) =>
      (credentials[field] ?? "") !== (initialCredentials.current[field] ?? "")
  );

  useEffect(() => {
    if (pendingExit) {
      confirmationRef.current?.querySelector<HTMLElement>("button")?.focus();
    } else {
      firstInputRef.current?.focus();
    }
  }, [pendingExit]);

  function requestExit(destination: "back" | "close") {
    if (isSubmitting) return;
    if (dirty) {
      setPendingExit(destination);
    } else {
      finishExit(destination);
    }
  }

  function finishExit(destination: "back" | "close") {
    if (destination === "back" && onBack) onBack();
    else {
      closing.current = true;
      onClose();
    }
  }

  function dismiss(event: { preventDefault: () => void }) {
    event.preventDefault();
    if (pendingExit) setPendingExit(null);
    else requestExit("close");
  }

  const status = server.connection_status;
  const isUpdatingCredentials =
    status === MCPConnectionStatus.CONNECTED ||
    status === MCPConnectionStatus.REAUTH_REQUIRED;
  const title = isUpdatingCredentials
    ? isTemplate
      ? t("header.manageCredentials.title")
      : t("header.manageApiKey.title")
    : isTemplate
      ? t("header.enterCredentials.title")
      : t("header.enterApiKey.title");
  const description = isUpdatingCredentials
    ? isTemplate
      ? t("intro.updateCredentials.text", { server: server.name })
      : t("intro.updateApiKey.text", { server: server.name })
    : isTemplate
      ? t("intro.enterCredentials.text", { server: server.name })
      : t("intro.enterApiKey.text", { server: server.name });
  const submitLabel = isSubmitting
    ? t("submitButton.saving.label")
    : isUpdatingCredentials
      ? isTemplate
        ? t("submitButton.updateCredentials.label")
        : t("submitButton.updateApiKey.label")
      : isTemplate
        ? t("submitButton.saveCredentials.label")
        : t("submitButton.saveApiKey.label");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isSubmitting || !hasRequiredCredentials) return;
    setIsSubmitting(true);
    setError(null);
    try {
      await onSubmit(credentials);
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : t("saveCredentialsError.message")
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <Modal.Content
      width="sm"
      skipOverlay={skipOverlay}
      preventAccidentalClose={false}
      onOpenAutoFocus={(event) => {
        event.preventDefault();
        firstInputRef.current?.focus();
      }}
      onEscapeKeyDown={dismiss}
      onInteractOutside={dismiss}
      onCloseAutoFocus={(event) => {
        if (onBack) {
          event.preventDefault();
          if (closing.current) onDismissFocus?.();
        }
      }}
    >
      {pendingExit ? (
        <div ref={confirmationRef} className="w-full">
          <UnsavedChangesModalContent
            onCancel={() => setPendingExit(null)}
            onDiscard={() => finishExit(pendingExit)}
          />
        </div>
      ) : (
        <>
          <Modal.Header
            icon={SvgKey}
            title={title}
            description={description}
            onClose={isSubmitting ? undefined : () => requestExit("close")}
          >
            {onBack && (
              <Button
                icon={SvgArrowLeft}
                prominence="tertiary"
                size="sm"
                disabled={isSubmitting}
                onClick={() => requestExit("back")}
              >
                {t("backButton.label")}
              </Button>
            )}
          </Modal.Header>
          <form onSubmit={submit} className="flex min-h-0 w-full flex-col">
            <Modal.Body alignItems="stretch">
              {error && (
                <div role="alert">
                  <Text font="secondary-body" color="text-03">
                    {error}
                  </Text>
                </div>
              )}
              {fields.map((field, index) => (
                <FormField key={field} name={field}>
                  <FormField.Label>
                    {field === "api_key"
                      ? t("apiKeyField.label")
                      : field.replace(/_/g, " ")}
                  </FormField.Label>
                  <FormField.Control asChild>
                    <InputPasswordTypeIn
                      ref={index === 0 ? firstInputRef : undefined}
                      name={field}
                      value={credentials[field] ?? ""}
                      onChange={(event) =>
                        setCredentials((previous) => ({
                          ...previous,
                          [field]: event.target.value,
                        }))
                      }
                      placeholder={
                        isTemplate
                          ? t("credentialField.placeholder", {
                              field: field.replace(/_/g, " "),
                            })
                          : t("apiKeyField.placeholder")
                      }
                      disabled={isSubmitting}
                      required
                    />
                  </FormField.Control>
                </FormField>
              ))}
            </Modal.Body>
            <Modal.Footer>
              <Button
                type="button"
                prominence="secondary"
                disabled={isSubmitting}
                onClick={() => requestExit(onBack ? "back" : "close")}
              >
                {t("cancelButton.label")}
              </Button>
              <Button
                type="submit"
                disabled={isSubmitting || !hasRequiredCredentials}
              >
                {submitLabel}
              </Button>
            </Modal.Footer>
          </form>
        </>
      )}
    </Modal.Content>
  );
}
