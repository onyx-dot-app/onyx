"use client";

import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import {
  ConfigurableSources,
  CredentialSchemaResponse,
  CredentialFieldSpec,
  FederatedConnectorCreateRequest,
  FederatedConnectorCreateResponse,
} from "@/lib/types";
import { getSourceMetadata } from "@/lib/sources";
import { SourceIcon } from "@/components/SourceIcon";
import { HeaderTitle } from "@/components/header/HeaderTitle";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useRouter } from "next/navigation";
import { AlertTriangle, Check, Loader2 } from "lucide-react";
import { BackButton } from "@/components/BackButton";

export interface FederatedConnectorFormProps {
  connector: ConfigurableSources;
}

interface CredentialForm {
  [key: string]: string;
}

interface FormState {
  credentials: CredentialForm;
  schema: Record<string, CredentialFieldSpec> | null;
  isLoadingSchema: boolean;
  schemaError: string | null;
}

async function fetchCredentialSchema(
  source: string
): Promise<CredentialSchemaResponse> {
  const response = await fetch(
    `/api/manage/admin/federated/sources/federated_${source}/credentials/schema`
  );
  if (!response.ok) {
    throw new Error(`Failed to fetch schema: ${response.statusText}`);
  }
  return response.json();
}

async function validateCredentials(
  source: string,
  credentials: CredentialForm
): Promise<{ success: boolean; message: string }> {
  try {
    const response = await fetch(
      `/api/manage/admin/federated/sources/federated_${source}/credentials/validate`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(credentials),
      }
    );

    const result = await response.json();
    return {
      success: result.success || false,
      message: result.message || "Validation failed",
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
    const response = await fetch("/api/manage/admin/federated", {
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

export default function FederatedConnectorForm({
  connector,
}: FederatedConnectorFormProps) {
  const router = useRouter();
  const sourceMetadata = getSourceMetadata(connector);
  const [formState, setFormState] = useState<FormState>({
    credentials: {},
    schema: null,
    isLoadingSchema: true,
    schemaError: null,
  });
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitMessage, setSubmitMessage] = useState<string | null>(null);
  const [submitSuccess, setSubmitSuccess] = useState<boolean | null>(null);
  const [isValidating, setIsValidating] = useState(false);

  // Fetch credential schema on component mount
  useEffect(() => {
    const loadSchema = async () => {
      try {
        setFormState((prev) => ({
          ...prev,
          isLoadingSchema: true,
          schemaError: null,
        }));
        const schemaResponse = await fetchCredentialSchema(connector);
        setFormState((prev) => ({
          ...prev,
          schema: schemaResponse.credentials,
          isLoadingSchema: false,
        }));
      } catch (error) {
        setFormState((prev) => ({
          ...prev,
          schemaError: `Failed to load credential schema: ${error}`,
          isLoadingSchema: false,
        }));
      }
    };

    loadSchema();
  }, [connector]);

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

      // Validate credentials before creating
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

      const result = await createFederatedConnector(
        connector,
        formState.credentials
      );

      setSubmitMessage(result.message);
      setSubmitSuccess(result.success);
      setIsSubmitting(false);

      if (result.success) {
        // Redirect after a short delay
        setTimeout(() => {
          router.push("/admin/indexing/status");
        }, 2000);
      }
    } catch (error) {
      setSubmitMessage(`Error: ${error}`);
      setSubmitSuccess(false);
      setIsSubmitting(false);
    }
  };

  const renderCredentialFields = () => {
    if (formState.isLoadingSchema) {
      return (
        <div className="flex items-center justify-center py-8">
          <Loader2 className="h-6 w-6 animate-spin" />
          <span className="ml-2">Loading credential schema...</span>
        </div>
      );
    }

    if (formState.schemaError) {
      return (
        <div className="flex items-center gap-2 p-3 rounded-md bg-red-50 text-red-700 border border-red-200">
          <AlertTriangle size={16} />
          <span className="text-sm">{formState.schemaError}</span>
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
    <div className="mx-auto container">
      <HeaderTitle>
        <div className="flex items-center gap-2">
          <SourceIcon sourceType={connector} iconSize={32} />
          <span>Setup {sourceMetadata.displayName} (Federated)</span>
          <div className="relative group">
            <AlertTriangle className="text-orange-500 cursor-help" size={20} />
            <div className="absolute left-1/2 transform -translate-x-1/2 top-full mt-2 px-3 py-2 bg-gray-900 text-white text-sm rounded-md opacity-0 group-hover:opacity-100 transition-opacity duration-200 pointer-events-none whitespace-nowrap z-10">
              {sourceMetadata.federatedTooltip ||
                "This is a federated connector. It will result in greater latency and lower search quality compared to regular connectors."}
              <div className="absolute bottom-full left-1/2 transform -translate-x-1/2 w-0 h-0 border-l-4 border-r-4 border-b-4 border-transparent border-b-gray-900"></div>
            </div>
          </div>
        </div>
      </HeaderTitle>

      <div className="mt-4 mb-4">
        <BackButton routerOverride="/admin/indexing/status" />
      </div>

      <Card className="mt-6">
        <CardHeader>
          <CardTitle>Connector Configuration</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            {renderCredentialFields()}

            <div className="flex gap-2 pt-4">
              <Button
                type="button"
                variant="outline"
                onClick={handleValidateCredentials}
                disabled={
                  isValidating || formState.isLoadingSchema || !formState.schema
                }
                className="flex items-center gap-2"
              >
                {isValidating ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Validating...
                  </>
                ) : (
                  "Validate Credentials"
                )}
              </Button>
              <Button
                type="submit"
                disabled={
                  isSubmitting || formState.isLoadingSchema || !formState.schema
                }
                className="flex items-center gap-2"
              >
                {isSubmitting ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Creating...
                  </>
                ) : (
                  "Create Federated Connector"
                )}
              </Button>
            </div>

            {submitMessage && (
              <div
                className={`flex items-center gap-2 p-3 rounded-md ${
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
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
