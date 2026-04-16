"use client";

import React, { useRef, useState } from "react";
import Modal from "@/refresh-components/Modal";
import { Callout } from "@/components/ui/callout";
import Text from "@/refresh-components/texts/Text";
import Button from "@/refresh-components/buttons/Button";
import { Label } from "@/components/Field";
import {
  CloudEmbeddingProvider,
  EmbeddingProvider,
} from "@/lib/indexing/interfaces";
import {
  EMBEDDING_PROVIDERS_ADMIN_URL,
  getFormattedProviderName,
} from "@/lib/indexing";
import { testEmbedding } from "@/lib/indexing/svc";
import { markdown } from "@opal/utils";
import { mutate } from "swr";
import { SvgSettings } from "@opal/icons";
import { useModal } from "@/refresh-components/contexts/ModalContext";

export interface EditEmbeddingModelModalProps {
  provider: CloudEmbeddingProvider;
}

export default function EditEmbeddingModelModal({
  provider,
}: EditEmbeddingModelModalProps) {
  const { toggle } = useModal();
  const close = () => toggle(false);

  const isLiteLLM = provider.provider_type === EmbeddingProvider.LITELLM;
  const isAzure = provider.provider_type === EmbeddingProvider.AZURE;
  const useFileUpload = provider.provider_type === EmbeddingProvider.GOOGLE;

  return (
    <Modal open onOpenChange={close}>
      <Modal.Content>
        <Modal.Header
          icon={SvgSettings}
          title={markdown(
            `Modify your *${getFormattedProviderName(
              provider.provider_type
            )}* ${isLiteLLM ? "configuration" : "key"}`
          )}
          onClose={close}
        />
        <Modal.Body>
          {isLiteLLM ? (
            <LiteLLMModalBody provider={provider} />
          ) : (
            <DefaultModalBody
              provider={provider}
              useFileUpload={useFileUpload}
              includeTargetUri={isAzure}
            />
          )}
        </Modal.Body>
      </Modal.Content>
    </Modal>
  );
}

// ============================================================================
// DefaultModalBody — handles every non-LiteLLM provider. Shows an API-key
// field (optionally via JSON file upload for Google) plus an optional Target
// URI field used by Azure.
// ============================================================================

interface DefaultModalBodyProps {
  provider: CloudEmbeddingProvider;
  useFileUpload: boolean;
  includeTargetUri?: boolean;
}

function DefaultModalBody({
  provider,
  useFileUpload,
  includeTargetUri = false,
}: DefaultModalBodyProps) {
  const { toggle } = useModal();
  const [apiKey, setApiKey] = useState("");
  const [targetUri, setTargetUri] = useState("");
  const [testError, setTestError] = useState<string>("");
  const [fileName, setFileName] = useState<string>("");
  const fileInputRef = useRef<HTMLInputElement>(null);

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
        modelName: "",
        apiKey,
        apiUrl: targetUri,
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
          api_url: targetUri,
          is_default_provider: false,
          is_configured: true,
        }),
      });

      if (!updateResponse.ok) {
        const errorData = await updateResponse.json();
        throw new Error(
          errorData.detail || "Failed to update provider- check your API key"
        );
      }

      await mutate(EMBEDDING_PROVIDERS_ADMIN_URL);
      toggle(false);
    } catch (error) {
      setTestError(
        error instanceof Error ? error.message : "An unknown error occurred"
      );
    }
  };

  const canSubmit = apiKey && (!includeTargetUri || targetUri);

  return (
    <>
      <Text as="p">
        You can modify your configuration by providing a new API key
        {includeTargetUri ? " or Target URI." : "."}
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
          <input
            type="password"
            className="border border-border rounded w-full py-2 px-3 bg-background-emphasis"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="Paste your API key here"
          />
        )}

        {includeTargetUri && (
          <>
            <Label className="mt-2">Target URI</Label>
            <input
              className="border border-border rounded w-full py-2 px-3 bg-background-emphasis"
              value={targetUri}
              onChange={(e) => setTargetUri(e.target.value)}
              placeholder="Paste your Target URI here"
            />
          </>
        )}

        {testError && (
          <Callout type="danger" title="Error">
            {testError}
          </Callout>
        )}

        {/* TODO(@raunakab): migrate to opal Button once className/iconClassName is resolved */}
        <Button
          className="mr-auto mt-4"
          onClick={() => handleSubmit()}
          disabled={!canSubmit}
        >
          Update Configuration
        </Button>
      </div>
    </>
  );
}

// ============================================================================
// LiteLLMModalBody — handles the LiteLLM proxy, which needs an API URL and a
// model name to test the connection against.
// ============================================================================

interface LiteLLMModalBodyProps {
  provider: CloudEmbeddingProvider;
}

function LiteLLMModalBody({ provider }: LiteLLMModalBodyProps) {
  const { toggle } = useModal();
  const [apiKey, setApiKey] = useState("");
  const [apiUrl, setApiUrl] = useState("");
  const [modelName, setModelName] = useState("");
  const [testError, setTestError] = useState<string>("");

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
          errorData.detail || "Failed to update provider- check your API URL"
        );
      }

      await mutate(EMBEDDING_PROVIDERS_ADMIN_URL);
      toggle(false);
    } catch (error) {
      setTestError(
        error instanceof Error ? error.message : "An unknown error occurred"
      );
    }
  };

  return (
    <>
      <Text as="p">
        You can modify your configuration by providing a new API key or API URL.
      </Text>

      <div className="flex flex-col gap-2">
        <Label className="mt-2">API Key</Label>
        <input
          type="password"
          className="border border-border rounded w-full py-2 px-3 bg-background-emphasis"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder="Paste your API key here"
        />

        <Label className="mt-2">API URL</Label>
        <input
          className="border border-border rounded w-full py-2 px-3 bg-background-emphasis"
          value={apiUrl}
          onChange={(e) => setApiUrl(e.target.value)}
          placeholder="Paste your API URL here"
        />

        <div>
          <Label className="mt-2">Test Model</Label>
          <Text as="p">
            Since you are using a liteLLM proxy, we&apos;ll need a model name to
            test the connection with.
          </Text>
        </div>
        <input
          className="border border-border rounded w-full py-2 px-3 bg-background-emphasis"
          value={modelName}
          onChange={(e) => setModelName(e.target.value)}
          placeholder="Paste your model name here"
        />

        {testError && (
          <Callout type="danger" title="Error">
            {testError}
          </Callout>
        )}

        {/* TODO(@raunakab): migrate to opal Button once className/iconClassName is resolved */}
        <Button
          className="mr-auto mt-4"
          onClick={() => handleSubmit()}
          disabled={!apiKey || !apiUrl || !modelName}
        >
          Update Configuration
        </Button>
      </div>
    </>
  );
}
