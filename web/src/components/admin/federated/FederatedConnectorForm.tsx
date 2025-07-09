"use client";

import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import {
  ConfigurableSources,
  CredentialSchemaResponse,
  CredentialFieldSpec,
  FederatedConnectorCreateRequest,
  FederatedConnectorDetail,
} from "@/lib/types";
import { getSourceMetadata } from "@/lib/sources";
import { SourceIcon } from "@/components/SourceIcon";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { useRouter } from "next/navigation";
import { AlertTriangle, Check, Loader2, Trash2Icon, Info } from "lucide-react";
import { BackButton } from "@/components/BackButton";
import Title from "@/components/ui/title";
import { EditableStringFieldDisplay } from "@/components/EditableStringFieldDisplay";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { DropdownMenuItemWithTooltip } from "@/components/ui/dropdown-menu-with-tooltip";
import { FiSettings } from "react-icons/fi";
import { usePopup } from "@/components/admin/connectors/Popup";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { Badge } from "@/components/ui/badge";

export interface FederatedConnectorFormProps {
  connector: ConfigurableSources;
  connectorId?: number; // Optional ID for editing existing connector
  preloadedConnectorData?: FederatedConnectorDetail;
  preloadedCredentialSchema?: CredentialSchemaResponse;
}

interface CredentialForm {
  [key: string]: string;
}

interface FormState {
  credentials: CredentialForm;
  schema: Record<string, CredentialFieldSpec> | null;
  schemaError: string | null;
  connectorError: string | null;
}

async function validateCredentials(
  source: string,
  credentials: CredentialForm
): Promise<{ success: boolean; message: string }> {
  try {
    const response = await fetch(
      `/api/federated/sources/federated_${source}/credentials/validate`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(credentials),
      }
    );

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      return {
        success: false,
        message:
          errorData.detail || `Validation failed: ${response.statusText}`,
      };
    }

    const result = await response.json();
    return {
      success: result,
      message: result ? "Credentials are valid" : "Credentials are invalid",
    };
  } catch (error) {
    return { success: false, message: `Validation error: ${error}` };
  }
}

async function createFederatedConnector(
  source: string,
  credentials: CredentialForm
): Promise<{ success: boolean; message: string }> {
  try {
    const response = await fetch("/api/federated", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        source: `federated_${source}`,
        credentials,
      } as FederatedConnectorCreateRequest),
    });

    if (response.ok) {
      return {
        success: true,
        message: "Federated connector created successfully!",
      };
    } else {
      const errorData = await response.json();
      return {
        success: false,
        message: errorData.detail || "Failed to create federated connector",
      };
    }
  } catch (error) {
    return { success: false, message: `Error: ${error}` };
  }
}

async function updateFederatedConnector(
  id: number,
  credentials: CredentialForm
): Promise<{ success: boolean; message: string }> {
  try {
    const response = await fetch(`/api/federated/${id}`, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        credentials,
      }),
    });

    if (response.ok) {
      return {
        success: true,
        message: "Federated connector updated successfully!",
      };
    } else {
      const errorData = await response.json();
      return {
        success: false,
        message: errorData.detail || "Failed to update federated connector",
      };
    }
  } catch (error) {
    return { success: false, message: `Error: ${error}` };
  }
}

async function deleteFederatedConnector(
  id: number
): Promise<{ success: boolean; message: string }> {
  try {
    const response = await fetch(`/api/federated/${id}`, {
      method: "DELETE",
    });

    if (response.ok) {
      return {
        success: true,
        message: "Federated connector deleted successfully!",
      };
    } else {
      const errorData = await response.json();
      return {
        success: false,
        message: errorData.detail || "Failed to delete federated connector",
      };
    }
  } catch (error) {
    return { success: false, message: `Error: ${error}` };
  }
}

export function FederatedConnectorForm({
  connector,
  connectorId,
  preloadedConnectorData,
  preloadedCredentialSchema,
}: FederatedConnectorFormProps) {
  const router = useRouter();
  const sourceMetadata = getSourceMetadata(connector);
  const isEditMode = connectorId !== undefined;
  const { popup, setPopup } = usePopup();

  const [formState, setFormState] = useState<FormState>({
    credentials: preloadedConnectorData?.credentials || {},
    schema: preloadedCredentialSchema?.credentials || null,
    schemaError: null,
    connectorError: null,
  });
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitMessage, setSubmitMessage] = useState<string | null>(null);
  const [submitSuccess, setSubmitSuccess] = useState<boolean | null>(null);
  const [isValidating, setIsValidating] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [isLoadingSchema, setIsLoadingSchema] = useState(
    !preloadedCredentialSchema
  );

  // Fetch credential schema if not preloaded
  useEffect(() => {
    const fetchCredentialSchema = async () => {
      if (!preloadedCredentialSchema) {
        setIsLoadingSchema(true);
        try {
          const response = await fetch(
            `/api/federated/sources/federated_${connector}/credentials/schema`
          );

          if (!response.ok) {
            throw new Error(
              `Failed to fetch credential schema: ${response.statusText}`
            );
          }

          const schemaData: CredentialSchemaResponse = await response.json();
          setFormState((prev) => ({
            ...prev,
            schema: schemaData.credentials,
            schemaError: null,
          }));
        } catch (error) {
          console.error("Error fetching credential schema:", error);
          setFormState((prev) => ({
            ...prev,
            schemaError: `Failed to load credential schema: ${error}`,
          }));
        } finally {
          setIsLoadingSchema(false);
        }
      }
    };

    fetchCredentialSchema();
  }, [connector, preloadedCredentialSchema]);

  // Show loading state at the top level if schema is loading
  if (isLoadingSchema) {
    return (
      <div className="mx-auto w-[800px]">
        {popup}
        <div className="flex flex-col items-center justify-center py-16">
          <Loader2 className="h-8 w-8 animate-spin text-blue-500 mb-4" />
          <div className="text-center">
            <p className="text-lg font-medium text-gray-700 mb-2">
              Loading credential schema...
            </p>
            <p className="text-sm text-gray-500">
              Retrieving required fields for this connector type
            </p>
          </div>
        </div>
      </div>
    );
  }

  const handleCredentialChange = (key: string, value: string) => {
    setFormState((prev) => ({
      ...prev,
      credentials: {
        ...prev.credentials,
        [key]: value,
      },
    }));
  };

  const handleValidateCredentials = async () => {
    if (!formState.schema) return;

    setIsValidating(true);
    setSubmitMessage(null);
    setSubmitSuccess(null);

    try {
      const result = await validateCredentials(
        connector,
        formState.credentials
      );
      setSubmitMessage(result.message);
      setSubmitSuccess(result.success);
    } catch (error) {
      setSubmitMessage(`Validation error: ${error}`);
      setSubmitSuccess(false);
    } finally {
      setIsValidating(false);
    }
  };

  const handleDeleteConnector = async () => {
    if (!connectorId) return;

    const confirmed = window.confirm(
      "Are you sure you want to delete this federated connector? This action cannot be undone."
    );

    if (!confirmed) return;

    setIsDeleting(true);

    try {
      const result = await deleteFederatedConnector(connectorId);

      if (result.success) {
        setPopup({
          message: result.message,
          type: "success",
        });
        // Redirect after a short delay
        setTimeout(() => {
          router.push("/admin/indexing/status");
        }, 500);
      } else {
        setPopup({
          message: result.message,
          type: "error",
        });
      }
    } catch (error) {
      setPopup({
        message: `Error deleting connector: ${error}`,
        type: "error",
      });
    } finally {
      setIsDeleting(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    setSubmitMessage(null);
    setSubmitSuccess(null);

    try {
      // Validate required fields
      if (formState.schema) {
        const missingRequired = Object.entries(formState.schema)
          .filter(
            ([key, field]) => field.required && !formState.credentials[key]
          )
          .map(([key]) => key);

        if (missingRequired.length > 0) {
          setSubmitMessage(
            `Missing required fields: ${missingRequired.join(", ")}`
          );
          setSubmitSuccess(false);
          setIsSubmitting(false);
          return;
        }
      }

      // Validate credentials before creating/updating
      const validation = await validateCredentials(
        connector,
        formState.credentials
      );
      if (!validation.success) {
        setSubmitMessage(`Credential validation failed: ${validation.message}`);
        setSubmitSuccess(false);
        setIsSubmitting(false);
        return;
      }

      // Create or update the connector
      const result =
        isEditMode && connectorId
          ? await updateFederatedConnector(connectorId, formState.credentials)
          : await createFederatedConnector(connector, formState.credentials);

      setSubmitMessage(result.message);
      setSubmitSuccess(result.success);
      setIsSubmitting(false);

      if (result.success) {
        // Redirect after a short delay
        setTimeout(() => {
          router.push("/admin/indexing/status");
        }, 500);
      }
    } catch (error) {
      setSubmitMessage(`Error: ${error}`);
      setSubmitSuccess(false);
      setIsSubmitting(false);
    }
  };

  const renderCredentialFields = () => {
    if (formState.schemaError) {
      return (
        <div className="flex items-center gap-2 p-3 rounded-md bg-red-50 text-red-700 border border-red-200">
          <AlertTriangle size={16} />
          <span className="text-sm">{formState.schemaError}</span>
        </div>
      );
    }

    if (formState.connectorError) {
      return (
        <div className="flex items-center gap-2 p-3 rounded-md bg-red-50 text-red-700 border border-red-200">
          <AlertTriangle size={16} />
          <span className="text-sm">{formState.connectorError}</span>
        </div>
      );
    }

    if (!formState.schema) {
      return (
        <div className="text-sm text-gray-500">
          No credential schema available for this connector type.
        </div>
      );
    }

    return (
      <>
        {Object.entries(formState.schema).map(([fieldKey, fieldSpec]) => (
          <div key={fieldKey} className="space-y-2 w-full">
            <Label htmlFor={fieldKey}>
              {fieldKey
                .replace(/_/g, " ")
                .replace(/\b\w/g, (l) => l.toUpperCase())}
              {fieldSpec.required && (
                <span className="text-red-500 ml-1">*</span>
              )}
            </Label>
            <Input
              id={fieldKey}
              type={fieldSpec.secret ? "password" : "text"}
              placeholder={
                fieldSpec.example
                  ? String(fieldSpec.example)
                  : fieldSpec.description
              }
              value={formState.credentials[fieldKey] || ""}
              onChange={(e) => handleCredentialChange(fieldKey, e.target.value)}
              className="w-full"
              required={fieldSpec.required}
            />
            {fieldSpec.description && (
              <p className="text-xs text-gray-500 mt-1">
                {fieldSpec.description}
              </p>
            )}
          </div>
        ))}
      </>
    );
  };

  return (
    <div className="mx-auto w-[800px]">
      {popup}
      <BackButton routerOverride="/admin/indexing/status" />

      <div className="flex items-center justify-between h-16 pb-2 border-b border-neutral-200 dark:border-neutral-600">
        <div className="my-auto">
          <SourceIcon iconSize={32} sourceType={connector} />
        </div>

        <div className="ml-2 overflow-hidden text-ellipsis whitespace-nowrap flex-1 mr-4">
          <div className="text-2xl font-bold text-text-default flex items-center gap-2">
            <span>
              {isEditMode ? "Edit" : "Setup"} {sourceMetadata.displayName}
            </span>
            <Badge variant="outline" className="text-xs">
              Federated
            </Badge>
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Info className="cursor-help" size={16} />
                </TooltipTrigger>
                <TooltipContent side="bottom" className="max-w-sm">
                  <p className="text-xs">
                    {sourceMetadata.federatedTooltip ||
                      "This is a federated connector. It will result in greater latency and lower search quality compared to regular connectors."}
                  </p>
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          </div>
        </div>

        {isEditMode && (
          <div className="ml-auto flex gap-x-2">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="outline"
                  size="sm"
                  className="flex items-center gap-x-1"
                >
                  <FiSettings className="h-4 w-4" />
                  <span className="text-sm ml-1">Manage</span>
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItemWithTooltip
                  onClick={handleDeleteConnector}
                  disabled={isDeleting}
                  className="flex items-center gap-x-2 cursor-pointer px-3 py-2 text-red-600 hover:text-red-700 dark:text-red-400 dark:hover:text-red-300"
                  tooltip={isDeleting ? "Deletion in progress" : undefined}
                >
                  <Trash2Icon className="h-4 w-4" />
                  <span>{isDeleting ? "Deleting..." : "Delete"}</span>
                </DropdownMenuItemWithTooltip>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        )}
      </div>

      <Title className="mb-2 mt-6" size="md">
        Connector Configuration
      </Title>

      <Card className="px-8 py-4">
        <CardContent className="p-0">
          <form onSubmit={handleSubmit} className="space-y-4">
            {renderCredentialFields()}

            <div className="flex gap-2 pt-4 w-full justify-end">
              {submitMessage && (
                <div
                  className={`flex items-center gap-2 p-2 rounded-md ${
                    submitSuccess
                      ? "bg-green-50 text-green-700 border border-green-200"
                      : "bg-red-50 text-red-700 border border-red-200"
                  }`}
                >
                  {submitSuccess ? (
                    <Check size={16} />
                  ) : (
                    <AlertTriangle size={16} />
                  )}
                  <span className="text-sm">{submitMessage}</span>
                </div>
              )}

              <Button
                type="button"
                variant="outline"
                onClick={handleValidateCredentials}
                disabled={isValidating || !formState.schema}
                className="flex items-center gap-2 self-center ml-auto"
              >
                {isValidating ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Validating...
                  </>
                ) : (
                  "Validate"
                )}
              </Button>
              <Button
                type="submit"
                disabled={isSubmitting || !formState.schema}
                className="flex items-center gap-2 self-center"
              >
                {isSubmitting ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    {isEditMode ? "Updating..." : "Creating..."}
                  </>
                ) : isEditMode ? (
                  "Update"
                ) : (
                  "Create"
                )}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
