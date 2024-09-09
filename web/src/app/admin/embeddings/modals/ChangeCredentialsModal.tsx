import React, { useRef, useState } from "react";
import { Modal } from "@/components/Modal";
import { Button, Text, Callout, Subtitle, Divider } from "@tremor/react";
import { Label, TextFormField } from "@/components/admin/connectors/Field";
import { CloudEmbeddingProvider } from "../../../../components/embedding/interfaces";
import {
  EMBEDDING_PROVIDERS_ADMIN_URL,
  LLM_PROVIDERS_ADMIN_URL,
} from "../../configuration/llm/constants";
import { mutate } from "swr";

export function ChangeCredentialsModal({
  provider,
  onConfirm,
  onCancel,
  onDeleted,
  useFileUpload,
  isProxy = false,
}: {
  provider: CloudEmbeddingProvider;
  onConfirm: () => void;
  onCancel: () => void;
  onDeleted: () => void;
  useFileUpload: boolean;
  isProxy?: boolean;
}) {
  const [apiKey, setApiKey] = useState("");
  const [apiUrl, setApiUrl] = useState("");
  const [modelName, setModelName] = useState("");

  const [testError, setTestError] = useState<string>("");
  const [fileName, setFileName] = useState<string>("");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isProcessing, setIsProcessing] = useState(false);
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
    setIsProcessing(true);

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
    } finally {
      setIsProcessing(false);
    }
  };

  const handleSubmit = async () => {
    setTestError("");
    const normalizedProviderType = provider.provider_type
      .toLowerCase()
      .split(" ")[0];
    try {
      const testResponse = await fetch("/api/admin/embedding/test-embedding", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider_type: normalizedProviderType,
          api_key: apiKey,
          api_url: apiUrl,
          model_name: modelName,
        }),
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
            `Failed to update provider- check your ${isProxy ? "API URL" : "API key"}`
        );
      }

      onConfirm();
    } catch (error) {
      setTestError(
        error instanceof Error ? error.message : "An unknown error occurred"
      );
    }
  };

  return (
    <Modal
      width="max-w-3xl"
      icon={provider.icon}
      title={`Modify your ${provider.provider_type} ${isProxy ? "Configuration" : "key"}`}
      onOutsideClick={onCancel}
    >
      <>
        <p className="mb-4">
          You can modify your configuration by providing a new API key
          {isProxy ? " or API URL." : "."}
        </p>

        <div className="mb-4 flex flex-col gap-y-2">
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
                className={`
                    border 
                    border-border 
                    rounded 
                    w-full 
                    py-2 
                    px-3 
                    bg-background-emphasis
                `}
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
                <Callout title="Error" color="red" className="mt-4">
                  {deletionError}
                </Callout>
              )}

              <div>
                <Label className="mt-2">Test Model</Label>
                <p>
                  Since you are using a liteLLM proxy, we&apos;ll need a model
                  name to test the connection with.
                </p>
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
                placeholder="Paste your API URL here"
              />

              {deletionError && (
                <Callout title="Error" color="red" className="mt-4">
                  {deletionError}
                </Callout>
              )}
            </>
          )}

          {testError && (
            <Callout title="Error" color="red" className="my-4">
              {testError}
            </Callout>
          )}

          <Button
            className="mr-auto mt-4"
            color="blue"
            onClick={() => handleSubmit()}
            disabled={!apiKey}
          >
            Update Configuration
          </Button>

          <Divider />

          <Subtitle className="mt-4 font-bold text-lg mb-2">
            You can also delete your configuration.
          </Subtitle>
          <Text className="mb-2">
            This is only possible if you have already switched to a different
            embedding type!
          </Text>

          <Button className="mr-auto" onClick={handleDelete} color="red">
            Delete Configuration
          </Button>
          {deletionError && (
            <Callout title="Error" color="red" className="mt-4">
              {deletionError}
            </Callout>
          )}
        </div>
      </>
    </Modal>
  );
}
