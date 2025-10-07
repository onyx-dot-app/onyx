"use client";

import { useState, useEffect } from "react";
import { Modal } from "@/components/Modal";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { FiKey, FiEye, FiEyeOff, FiAlertCircle } from "react-icons/fi";

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
  onSubmit: (serverId: number, apiKey: string) => void;
  onSubmitCredentials?: (
    serverId: number,
    credentials: Record<string, string>
  ) => void;
  onSuccess?: () => void;
  isAuthenticated?: boolean;
  existingCredentials?: Record<string, string>;
}

export function MCPApiKeyModal({
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
      const hasAllFields = authTemplate!.required_fields.every(
        (field) => credentials[field]?.trim()
      );
      if (!hasAllFields) return;

      setIsSubmitting(true);
      try {
        if (onSubmitCredentials) {
          await onSubmitCredentials(serverId, credentials);
        }
        setCredentials({});
        if (onSuccess) {
          onSuccess();
        }
        onClose();
      } catch (error) {
        console.error("Error submitting credentials:", error);
        let errorMessage = "Failed to save credentials";
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
          onSuccess();
        }
        onClose();
      } catch (error) {
        console.error("Error submitting API key:", error);
        let errorMessage = "Failed to save API key";
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

  const credsType = isTemplateMode ? "Credentials" : "API Key";
  return (
    <Modal
      title={
        <div className="flex items-center space-x-2">
          <FiKey className="h-5 w-5" />
          <span>
            {isAuthenticated ? `Manage ${credsType}` : `Enter ${credsType}`}
          </span>
        </div>
      }
      onOutsideClick={handleClose}
      width="max-w-md"
    >
      <div className="space-y-4">
        <div>
          <p className="text-sm text-subtle mb-2">
            {isAuthenticated
              ? `Update your ${credsType} for ${serverName}.`
              : `Enter your ${credsType} for ${serverName} to enable authentication.`}
          </p>
          <p className="text-xs text-subtle">
            {isAuthenticated
              ? "Changes will be validated against the server before being saved."
              : `Your ${credsType} will be validated against the server and stored securely.`}
          </p>
        </div>

        {error && (
          <div className="flex items-center space-x-2 p-3 bg-red-50 border border-red-200 rounded-md text-red-800 text-sm">
            <FiAlertCircle className="h-4 w-4 flex-shrink-0" />
            <span>{error}</span>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          {isTemplateMode ? (
            // Template-based credential fields
            <div className="space-y-4">
              {authTemplate!.required_fields.map((field) => (
                <div key={field} className="space-y-2">
                  <Label htmlFor={field}>
                    {field
                      .replace(/_/g, " ")
                      .replace(/\b\w/g, (l) => l.toUpperCase())}
                  </Label>
                  <div className="relative">
                    <Input
                      id={field}
                      type={showCredentials[field] ? "text" : "password"}
                      value={credentials[field] || ""}
                      onChange={(e) => updateCredential(field, e.target.value)}
                      placeholder={`Enter your ${field.replace(/_/g, " ")}`}
                      className="pr-10"
                      required
                    />
                    <button
                      type="button"
                      onClick={() => toggleCredentialVisibility(field)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-subtle hover:text-emphasis"
                    >
                      {showCredentials[field] ? (
                        <FiEyeOff className="h-4 w-4" />
                      ) : (
                        <FiEye className="h-4 w-4" />
                      )}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            // Legacy API key field
            <div className="space-y-2">
              <Label htmlFor="apiKey">{credsType}</Label>
              <div className="relative">
                <Input
                  id="apiKey"
                  type={showApiKey ? "text" : "password"}
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder={`Enter your ${credsType}`}
                  className="pr-10"
                  required
                />
                <button
                  type="button"
                  onClick={() => setShowApiKey(!showApiKey)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-subtle hover:text-emphasis"
                >
                  {showApiKey ? (
                    <FiEyeOff className="h-4 w-4" />
                  ) : (
                    <FiEye className="h-4 w-4" />
                  )}
                </button>
              </div>
            </div>
          )}

          <div className="flex justify-end space-x-2 pt-4">
            <Button
              type="button"
              variant="outline"
              onClick={handleClose}
              disabled={isSubmitting}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={
                isSubmitting ||
                (isTemplateMode
                  ? !authTemplate!.required_fields.every(
                      (field) => credentials[field]?.trim()
                    )
                  : !apiKey.trim())
              }
            >
              {isSubmitting
                ? "Saving..."
                : isAuthenticated
                  ? `Update ${credsType}`
                  : `Save ${credsType}`}
            </Button>
          </div>
        </form>
      </div>
    </Modal>
  );
}
