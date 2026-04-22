"use client";

import { useRef, useState } from "react";
import { markdown } from "@opal/utils";
import { Button, Divider, MessageCard } from "@opal/components";
import { SvgArrowExchange } from "@opal/icons";
import { SvgOnyxLogo } from "@opal/logos";
import { InputHorizontal, InputVertical } from "@opal/layouts";
import * as GeneralLayouts from "@/layouts/general-layouts";
import Modal from "@/refresh-components/Modal";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import Switch from "@/refresh-components/inputs/Switch";
import type {
  CloudEmbeddingProvider,
  ConfiguredEmbeddingProvider,
} from "@/lib/indexing/interfaces";
import { getFormattedProviderName } from "@/lib/indexing";
import { connectEmbeddingProvider } from "@/lib/indexing/svc";
import { ApiKeyField, ApiUrlField, GoogleCredentialsField } from "./shared";

// ---------------------------------------------------------------------------
// Shared modal shell
// ---------------------------------------------------------------------------

interface ModalShellProps {
  provider: CloudEmbeddingProvider;
  isEditing: boolean;
  isValid: boolean;
  isSubmitting: boolean;
  errorMsg: string;
  onSubmit: () => void;
  onCancel: () => void;
  children: React.ReactNode;
}

function ModalShell({
  provider,
  isEditing,
  isValid,
  isSubmitting,
  errorMsg,
  onSubmit,
  onCancel,
  children,
}: ModalShellProps) {
  const providerName = getFormattedProviderName(provider.provider_type);

  return (
    <Modal open onOpenChange={(isOpen) => !isOpen && onCancel()}>
      <Modal.Content width="md">
        <Modal.Header
          icon={provider.icon}
          moreIcon1={SvgArrowExchange}
          moreIcon2={SvgOnyxLogo}
          title={
            isEditing ? `Manage ${providerName}` : `Set up ${providerName}`
          }
          description={
            isEditing
              ? `Manage ${providerName} provider and model details.`
              : `Connect to ${providerName} and set up your ${providerName} embedding models.`
          }
          onClose={onCancel}
        />
        <Modal.Body twoTone>
          <GeneralLayouts.Section gap={1}>
            {children}

            {errorMsg && (
              <MessageCard
                variant="error"
                title="Error"
                description={errorMsg}
              />
            )}
          </GeneralLayouts.Section>
        </Modal.Body>
        <Modal.Footer>
          <Button prominence="secondary" onClick={onCancel}>
            Cancel
          </Button>
          <Button disabled={!isValid || isSubmitting} onClick={onSubmit}>
            {isSubmitting
              ? isEditing
                ? "Updating..."
                : "Connecting..."
              : isEditing
                ? "Update"
                : "Connect"}
          </Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Shared hook for submit logic
// ---------------------------------------------------------------------------

function useProviderSubmit(
  provider: CloudEmbeddingProvider,
  apiKey: string,
  apiUrl: string,
  onSubmit: () => void
) {
  const [errorMsg, setErrorMsg] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async () => {
    setErrorMsg("");
    setIsSubmitting(true);
    try {
      await connectEmbeddingProvider({
        providerType: provider.provider_type,
        apiKey,
        apiUrl,
      });
      onSubmit();
    } catch (error: unknown) {
      setErrorMsg(
        error instanceof Error ? error.message : "An unknown error occurred"
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  return { errorMsg, isSubmitting, handleSubmit };
}

// ---------------------------------------------------------------------------
// Shared props
// ---------------------------------------------------------------------------

export interface ProviderModalProps {
  provider: CloudEmbeddingProvider;
  existingCredentials?: ConfiguredEmbeddingProvider;
  onSubmit: () => void;
  onCancel: () => void;
}

// ---------------------------------------------------------------------------
// Standard provider modal (OpenAI, Cohere, Voyage)
// ---------------------------------------------------------------------------

export function StandardProviderModal({
  provider,
  existingCredentials,
  onSubmit,
  onCancel,
}: ProviderModalProps) {
  const isEditing = !!existingCredentials;
  const providerName = getFormattedProviderName(provider.provider_type);
  const [apiKey, setApiKey] = useState(existingCredentials?.api_key ?? "");

  const { errorMsg, isSubmitting, handleSubmit } = useProviderSubmit(
    provider,
    apiKey,
    "",
    onSubmit
  );

  return (
    <ModalShell
      provider={provider}
      isEditing={isEditing}
      isValid={!!apiKey}
      isSubmitting={isSubmitting}
      errorMsg={errorMsg}
      onSubmit={handleSubmit}
      onCancel={onCancel}
    >
      <ApiKeyField
        apiLink={provider.apiLink}
        providerName={providerName}
        value={apiKey}
        onChange={setApiKey}
      />
    </ModalShell>
  );
}

// ---------------------------------------------------------------------------
// Google provider modal (JSON file upload)
// ---------------------------------------------------------------------------

export function GoogleProviderModal({
  provider,
  existingCredentials,
  onSubmit,
  onCancel,
}: ProviderModalProps) {
  const isEditing = !!existingCredentials;
  const [apiKey, setApiKey] = useState(existingCredentials?.api_key ?? "");
  const [fileName, setFileName] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    setFileName("");
    if (!file) return;
    setFileName(file.name);
    try {
      const content = JSON.parse(await file.text());
      setApiKey(JSON.stringify(content));
    } catch {
      setApiKey("");
    }
  };

  const { errorMsg, isSubmitting, handleSubmit } = useProviderSubmit(
    provider,
    apiKey,
    "",
    onSubmit
  );

  return (
    <ModalShell
      provider={provider}
      isEditing={isEditing}
      isValid={!!apiKey}
      isSubmitting={isSubmitting}
      errorMsg={errorMsg}
      onSubmit={handleSubmit}
      onCancel={onCancel}
    >
      <GoogleCredentialsField
        fileInputRef={fileInputRef}
        fileName={fileName}
        onFileUpload={handleFileUpload}
      />
    </ModalShell>
  );
}

// ---------------------------------------------------------------------------
// Azure provider modal (Target URL + API Key)
// ---------------------------------------------------------------------------

export function AzureProviderModal({
  provider,
  existingCredentials,
  onSubmit,
  onCancel,
}: ProviderModalProps) {
  const isEditing = !!existingCredentials;
  const providerName = getFormattedProviderName(provider.provider_type);
  const [apiKey, setApiKey] = useState(existingCredentials?.api_key ?? "");
  const [apiUrl, setApiUrl] = useState(existingCredentials?.api_url ?? "");

  const { errorMsg, isSubmitting, handleSubmit } = useProviderSubmit(
    provider,
    apiKey,
    apiUrl,
    onSubmit
  );

  return (
    <ModalShell
      provider={provider}
      isEditing={isEditing}
      isValid={!!apiUrl && !!apiKey}
      isSubmitting={isSubmitting}
      errorMsg={errorMsg}
      onSubmit={handleSubmit}
      onCancel={onCancel}
    >
      <ApiUrlField
        title="Target URL"
        placeholder="https://your_resource_name.openai.azure.com/openai/v1/embeddings"
        value={apiUrl}
        onChange={setApiUrl}
      />
      <ApiKeyField
        apiLink={provider.apiLink}
        providerName={providerName}
        value={apiKey}
        onChange={setApiKey}
      />
    </ModalShell>
  );
}

// ---------------------------------------------------------------------------
// LiteLLM provider modal (full config)
// ---------------------------------------------------------------------------

export function LiteLLMProviderModal({
  provider,
  existingCredentials,
  onSubmit,
  onCancel,
}: ProviderModalProps) {
  const isEditing = !!existingCredentials;
  const providerName = getFormattedProviderName(provider.provider_type);
  const [apiKey, setApiKey] = useState(existingCredentials?.api_key ?? "");
  const [apiUrl, setApiUrl] = useState(existingCredentials?.api_url ?? "");
  const [modelName, setModelName] = useState("");
  const [modelDim, setModelDim] = useState("");
  const [queryPrefix, setQueryPrefix] = useState("");
  const [passagePrefix, setPassagePrefix] = useState("");
  const [normalize, setNormalize] = useState(false);

  const { errorMsg, isSubmitting, handleSubmit } = useProviderSubmit(
    provider,
    apiKey,
    apiUrl,
    onSubmit
  );

  return (
    <ModalShell
      provider={provider}
      isEditing={isEditing}
      isValid={!!apiUrl && !!modelName && !!modelDim}
      isSubmitting={isSubmitting}
      errorMsg={errorMsg}
      onSubmit={handleSubmit}
      onCancel={onCancel}
    >
      <ApiUrlField
        title="API Base URL"
        placeholder="https://..."
        subDescription={`Paste your ${providerName}-compatible endpoint URL.`}
        value={apiUrl}
        onChange={setApiUrl}
      />

      <ApiKeyField
        apiLink={provider.apiLink}
        providerName={providerName}
        value={apiKey}
        onChange={setApiKey}
      />

      <InputVertical
        title="Model Name"
        subDescription={`Onyx will connect to this model on your ${providerName} proxy.`}
      >
        <InputTypeIn
          placeholder="model-name"
          value={modelName}
          onChange={(e) => setModelName(e.target.value)}
        />
      </InputVertical>

      <Divider paddingParallel="fit" paddingPerpendicular="fit" />

      <InputVertical
        title="Model Dimension"
        subDescription="Number of dimensions in the embeddings generated by this model."
      >
        <InputTypeIn
          inputMode="numeric"
          placeholder="e.g., 768"
          value={modelDim}
          onChange={(e) => setModelDim(e.target.value)}
        />
      </InputVertical>

      <InputVertical
        title="Query Prefix"
        suffix="optional"
        subDescription="This is prepended to search queries before passing to the model, if required by your embedding model. Incorrect or missing prefixes will degrade embedding quality."
      >
        <InputTypeIn
          placeholder="e.g., 'query: '"
          value={queryPrefix}
          onChange={(e) => setQueryPrefix(e.target.value)}
        />
      </InputVertical>

      <InputVertical
        title="Passage Prefix"
        suffix="optional"
        subDescription="This is prepended to indexed document chunks before passing to the model, if required by your embedding model. Incorrect or missing prefixes will degrade embedding quality."
      >
        <InputTypeIn
          placeholder="e.g., 'passage: '"
          value={passagePrefix}
          onChange={(e) => setPassagePrefix(e.target.value)}
        />
      </InputVertical>

      <InputHorizontal
        title="Normalize Embeddings"
        description="Normalize the embeddings generated by the model. Recommended for most models unless your embedding model documentation specifies otherwise."
        withLabel
      >
        <Switch checked={normalize} onCheckedChange={setNormalize} />
      </InputHorizontal>
    </ModalShell>
  );
}
