"use client";

import React, { useRef, useState } from "react";
import Modal from "@/refresh-components/Modal";
import { Callout } from "@/components/ui/callout";
import Text from "@/refresh-components/texts/Text";
import Separator from "@/refresh-components/Separator";
import Button from "@/refresh-components/buttons/Button";
import { Label } from "@/components/Field";
import {
  CloudEmbeddingProvider,
  getFormattedProviderName,
} from "@/components/embedding/interfaces";
import {
  EMBEDDING_PROVIDERS_ADMIN_URL,
  LLM_PROVIDERS_ADMIN_URL,
} from "@/app/admin/configuration/llm/constants";
import { mutate } from "swr";
import { testEmbedding } from "@/app/admin/embeddings/pages/utils";
import { SvgSettings } from "@opal/icons";

export interface ChangeCredentialsModalProps {
  provider: CloudEmbeddingProvider;
  onConfirm: () => void;
  onCancel: () => void;
  onDeleted: () => void;
  useFileUpload: boolean;
  isProxy?: boolean;
  isAzure?: boolean;
}

export default function ChangeCredentialsModal({
  provider,
  onConfirm,
  onCancel,
  onDeleted,
  useFileUpload,
  isProxy = false,
  isAzure = false,
}: ChangeCredentialsModalProps) {
  const [apiKey, setApiKey] = useState("");
  const [apiUrl, setApiUrl] = useState("");
  const [modelName, setModelName] = useState("");
  const [testError, setTestError] = useState<string>("");
  const [fileName, setFileName] = useState<string>("");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [deletionError, setDeletionError] = useState<string>("");

  const clearFileInput = () => {
    setFileName("");
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  const handleFileUpload = async (
    event: React.ChangeEvent<HTMLInputElement>
  ) => {
    const file = event.target.files?.[0];
    setFileName("");

    if (file) {
      setFileName(file.name);
      try {
        setDeletionError("");
        const fileContent = await file.text();
        let jsonContent;
        try {
          jsonContent = JSON.parse(fileContent);
          setApiKey(JSON.stringify(jsonContent));
        } catch (parseError) {
          throw new Error(
            "Failed to parse JSON file. Please ensure it's a valid JSON."
          );
        }
      } catch (error) {
        setTestError(
          error instanceof Error
            ? error.message
            : "An unknown error occurred while processing the file."
        );
        setApiKey("");
        clearFileInput();
      }
    }
  };

  const handleDelete = async () => {
    setDeletionError("");

    try {
      const response = await fetch(
        `${EMBEDDING_PROVIDERS_ADMIN_URL}/${provider.provider_type.toLowerCase()}`,
        {
          method: "DELETE",
        }
      );

      if (!response.ok) {
        const errorData = await response.json();
        setDeletionError(errorData.detail);
        return;
      }

      mutate(LLM_PROVIDERS_ADMIN_URL);
      onDeleted();
    } catch (error) {
      setDeletionError(
        error instanceof Error ? error.message : "An unknown error occurred"
      );
    }
  };

  const handleSubmit = async () => {
    setTestError("");
    const normalizedProviderType = provider.provider_type
      .toLowerCase()
      .split(" ")[0];

    if (!normalizedProviderType) {
      setTestError("Provider type is invalid or missing.");
      return;
    }

    try {
      const testResponse = await testEmbedding({
        provider_type: normalizedProviderType,
        modelName,
        apiKey,
        apiUrl,
        apiVersion: null,
        deploymentName: null,
      });

      if (!testResponse.ok) {
        const errorMsg = (await testResponse.json()).detail;
        throw new Error(errorMsg);
      }

      const updateResponse = await fetch(EMBEDDING_PROVIDERS_ADMIN_URL, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider_type: normalizedProviderType,
          api_key: apiKey,
          api_url: apiUrl,
          is_default_provider: false,
          is_configured: true,
        }),
      });

      if (!updateResponse.ok) {
        const errorData = await updateResponse.json();
        throw new Error(
          errorData.detail ||
            `Failed to update provider- check your ${
              isProxy ? "API URL" : "API key"
            }`
        );
      }

      // Refresh cached provider details so the rest of the form sees the new key without forcing a re-index
      await mutate(EMBEDDING_PROVIDERS_ADMIN_URL);

      onConfirm();
    } catch (error) {
      setTestError(
        error instanceof Error ? error.message : "An unknown error occurred"
      );
    }
  };
  return (
    <Modal open onOpenChange={onCancel}>
      <Modal.Content>
        <Modal.Header
          icon={SvgSettings}
          title={`Modify your ${getFormattedProviderName(
            provider.provider_type
          )} ${isProxy ? "Configuration" : "key"}`}
          onClose={onCancel}
        />
        <Modal.Body>
          {!isAzure && (
            <>
              <Text as="p">
                You can modify your configuration by providing a new API key
                {isProxy ? " or API URL." : "."}
              </Text>

              <div className="flex flex-col gap-2">
                <Label className="mt-2">API Key</Label>
                {useFileUpload ? (
                  <>
                    <Label className="mt-2">Upload JSON File</Label>
                    <input
                      ref={fileInputRef}
                      type="file"
                      accept=".json"
                      onChange={handleFileUpload}
                      className="text-lg w-full p-1"
                    />
                    {fileName && <p>Uploaded file: {fileName}</p>}
                  </>
                ) : (
                  <>
                    <input
                      className="border border-border rounded w-full py-2 px-3 bg-background-emphasis"
                      value={apiKey}
                      onChange={(e: any) => setApiKey(e.target.value)}
                      placeholder="Paste your API key here"
                    />
                  </>
                )}

                {isProxy && (
                  <>
                    <Label className="mt-2">API URL</Label>

                    <input
                      className={`
                          border
                          border-border
                          rounded
                          w-full
                          py-2
                          px-3
                          bg-background-emphasis
                      `}
                      value={apiUrl}
                      onChange={(e: any) => setApiUrl(e.target.value)}
                      placeholder="Paste your API URL here"
                    />

                    {deletionError && (
                      <Callout type="danger" title="Error">
                        {deletionError}
                      </Callout>
                    )}

                    <div>
                      <Label className="mt-2">Test Model</Label>
                      <Text as="p">
                        Since you are using a liteLLM proxy, we&apos;ll need a
                        model name to test the connection with.
                      </Text>
                    </div>
                    <input
                      className={`
                       border
                       border-border
                       rounded
                       w-full
                       py-2
                       px-3
                       bg-background-emphasis
                   `}
                      value={modelName}
                      onChange={(e: any) => setModelName(e.target.value)}
                      placeholder="Paste your model name here"
                    />
                  </>
                )}

                {testError && (
                  <Callout type="danger" title="Error">
                    {testError}
                  </Callout>
                )}

                <Button
                  className="mr-auto mt-4"
                  onClick={() => handleSubmit()}
                  disabled={!apiKey}
                >
                  Update Configuration
                </Button>

                <Separator />
              </div>
            </>
          )}

          <Text as="p" className="mt-4 font-bold">
            You can delete your configuration.
          </Text>
          <Text as="p">
            This is only possible if you have already switched to a different
            embedding type!
          </Text>

          <Button className="mr-auto" onClick={handleDelete} danger>
            Delete Configuration
          </Button>
          {deletionError && (
            <Callout type="danger" title="Error">
              {deletionError}
            </Callout>
          )}
        </Modal.Body>
      </Modal.Content>
    </Modal>
  );
}
