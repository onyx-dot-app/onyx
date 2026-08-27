"use client";

import { useState, useEffect } from "react";
import { useTranslations } from "next-intl";
import { Modal } from "@opal/components";
import { Button } from "@opal/components";
import { Input } from "@/components/ui/input";
import { Label } from "@opal/layouts";
import Text from "@/refresh-components/texts/Text";
import { SvgAlertCircle, SvgEye, SvgEyeClosed, SvgKey } from "@opal/icons";
interface MCPAuthTemplate {
  headers: Array<{ name: string; value: string }>;
  request_body_params: Array<{ path: string; value: string }>;
  required_fields: string[];
}

interface MCPApiKeyModalProps {
  isOpen: boolean;
  onClose: () => void;
  serverName: string;
  serverId: number;
  authTemplate?: MCPAuthTemplate;
  onSubmit: (serverId: number, apiKey: string) => Promise<void> | void;
  onSubmitCredentials?: (
    serverId: number,
    credentials: Record<string, string>
  ) => Promise<void> | void;
  onSuccess?: () => Promise<void> | void;
  isAuthenticated?: boolean;
  existingCredentials?: Record<string, string>;
}

export default function MCPApiKeyModal({
  isOpen,
  onClose,
  serverName,
  serverId,
  authTemplate,
  onSubmit,
  onSubmitCredentials,
  onSuccess,
  isAuthenticated = false,
  existingCredentials,
}: MCPApiKeyModalProps) {
  const t = useTranslations("chat.mcpApiKey");
  const [apiKey, setApiKey] = useState("");
  const [showApiKey, setShowApiKey] = useState(false);
  const [credentials, setCredentials] = useState<Record<string, string>>({});
  const [showCredentials, setShowCredentials] = useState<
    Record<string, boolean>
  >({});
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isTemplateMode =
    authTemplate && authTemplate.required_fields.length > 0;

  // Initialize form with existing credentials when modal opens
  useEffect(() => {
    if (isOpen && existingCredentials) {
      if (isTemplateMode) {
        // For template mode, set the credentials object
        setCredentials(existingCredentials);
      } else {
        // For legacy API key mode, set the api_key field
        const apiKeyValue = existingCredentials.api_key || "";
        setApiKey(apiKeyValue);
      }
    }
  }, [isOpen, existingCredentials, isTemplateMode]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null); // Clear any previous errors

    if (isTemplateMode) {
      // Check all required fields are filled
      const hasAllFields = authTemplate!.required_fields.every((field) =>
        credentials[field]?.trim()
      );
      if (!hasAllFields) return;

      setIsSubmitting(true);
      try {
        if (onSubmitCredentials) {
          await onSubmitCredentials(serverId, credentials);
        }
        setCredentials({});
        if (onSuccess) {
          await onSuccess();
        }
        onClose();
      } catch (error) {
        console.error("Error submitting credentials:", error);
        let errorMessage = t("saveCredentialsError.message");
        if (error instanceof Error) {
          errorMessage = error.message;
        } else if (typeof error === "string") {
          errorMessage = error;
        }
        setError(errorMessage);
      } finally {
        setIsSubmitting(false);
      }
    } else {
      // Legacy API key mode
      if (!apiKey.trim()) return;

      setIsSubmitting(true);
      try {
        await onSubmit(serverId, apiKey);
        setApiKey("");
        if (onSuccess) {
          await onSuccess();
        }
        onClose();
      } catch (error) {
        console.error("Error submitting API key:", error);
        let errorMessage = t("saveApiKeyError.message");
        if (error instanceof Error) {
          errorMessage = error.message;
        } else if (typeof error === "string") {
          errorMessage = error;
        }
        setError(errorMessage);
      } finally {
        setIsSubmitting(false);
      }
    }
  };

  const handleClose = () => {
    setApiKey("");
    setShowApiKey(false);
    setCredentials({});
    setShowCredentials({});
    setError(null);
    onClose();
  };

  const toggleCredentialVisibility = (field: string) => {
    setShowCredentials((prev) => ({
      ...prev,
      [field]: !prev[field],
    }));
  };

  const updateCredential = (field: string, value: string) => {
    setCredentials((prev) => ({
      ...prev,
      [field]: value,
    }));
  };

  // Credentials and API key wording differ per branch, so each variant is a
  // whole message instead of a sentence built from fragments.
  const modalTitle = isAuthenticated
    ? isTemplateMode
      ? t("header.manageCredentials.title")
      : t("header.manageApiKey.title")
    : isTemplateMode
      ? t("header.enterCredentials.title")
      : t("header.enterApiKey.title");
  const introText = isAuthenticated
    ? isTemplateMode
      ? t("intro.updateCredentials.text", { server: serverName })
      : t("intro.updateApiKey.text", { server: serverName })
    : isTemplateMode
      ? t("intro.enterCredentials.text", { server: serverName })
      : t("intro.enterApiKey.text", { server: serverName });
  const validationText = isAuthenticated
    ? t("validationNote.authenticated.text")
    : isTemplateMode
      ? t("validationNote.credentials.text")
      : t("validationNote.apiKey.text");
  const submitLabel = isSubmitting
    ? t("submitButton.saving.label")
    : isAuthenticated
      ? isTemplateMode
        ? t("submitButton.updateCredentials.label")
        : t("submitButton.updateApiKey.label")
      : isTemplateMode
        ? t("submitButton.saveCredentials.label")
        : t("submitButton.saveApiKey.label");

  return (
    <Modal open={isOpen} onOpenChange={handleClose}>
      <Modal.Content width="sm" height="sm">
        <Modal.Header icon={SvgKey} title={modalTitle} onClose={handleClose} />
        <Modal.Body>
          <Text as="p">{introText}</Text>
          <Text as="p" text02>
            {validationText}
          </Text>

          {error && (
            <div className="flex items-center space-x-2 p-3 bg-red-50 border border-red-200 rounded-md text-red-800 text-sm">
              <SvgAlertCircle className="h-4 w-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            {isTemplateMode ? (
              // Template-based credential fields
              <div className="space-y-4">
                {authTemplate!.required_fields.map((field) => (
                  <div key={field} className="space-y-2">
                    <Label label={field}>
                      <Text>
                        {field
                          .replace(/_/g, " ")
                          .replace(/\b\w/g, (l) => l.toUpperCase())}
                      </Text>
                    </Label>
                    <div className="relative">
                      <Input
                        id={field}
                        type={showCredentials[field] ? "text" : "password"}
                        value={credentials[field] || ""}
                        onChange={(e) =>
                          updateCredential(field, e.target.value)
                        }
                        placeholder={t("credentialField.placeholder", {
                          field: field.replace(/_/g, " "),
                        })}
                        className="pr-10"
                        required
                      />
                      <button
                        type="button"
                        onClick={() => toggleCredentialVisibility(field)}
                        className="absolute right-3 top-1/2 -translate-y-1/2 text-subtle hover:text-emphasis"
                        aria-label={
                          showCredentials[field]
                            ? t("credentialVisibilityButton.hideAriaLabel")
                            : t("credentialVisibilityButton.showAriaLabel")
                        }
                      >
                        {showCredentials[field] ? (
                          <SvgEyeClosed className="h-4 w-4" />
                        ) : (
                          <SvgEye className="h-4 w-4" />
                        )}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              // Legacy API key field
              <div className="space-y-2">
                <Label label="apiKey">
                  <Text>{t("apiKeyField.label")}</Text>
                </Label>
                <div className="relative">
                  <Input
                    id="apiKey"
                    type={showApiKey ? "text" : "password"}
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                    placeholder={t("apiKeyField.placeholder")}
                    className="pr-10"
                    required
                  />
                  <button
                    type="button"
                    onClick={() => setShowApiKey(!showApiKey)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-subtle hover:text-emphasis"
                    aria-label={
                      showApiKey
                        ? t("apiKeyVisibilityButton.hideAriaLabel")
                        : t("apiKeyVisibilityButton.showAriaLabel")
                    }
                  >
                    {showApiKey ? (
                      <SvgEyeClosed className="h-4 w-4" />
                    ) : (
                      <SvgEye className="h-4 w-4" />
                    )}
                  </button>
                </div>
              </div>
            )}

            <div className="flex justify-end space-x-2 pt-4">
              <Button
                disabled={isSubmitting}
                prominence="secondary"
                onClick={handleClose}
              >
                {t("cancelButton.label")}
              </Button>
              <Button
                disabled={
                  isSubmitting ||
                  (isTemplateMode
                    ? !authTemplate!.required_fields.every((field) =>
                        credentials[field]?.trim()
                      )
                    : !apiKey.trim())
                }
                type="submit"
              >
                {submitLabel}
              </Button>
            </div>
          </form>
        </Modal.Body>
      </Modal.Content>
    </Modal>
  );
}
