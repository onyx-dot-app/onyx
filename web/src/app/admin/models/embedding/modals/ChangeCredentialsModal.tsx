import React, { useRef, useState } from "react";
import { Modal } from "@/components/Modal";
import { Button, Text, Callout, Subtitle, Divider } from "@tremor/react";
import { Label, TextFormField } from "@/components/admin/connectors/Field";
import { CloudEmbeddingProvider } from "../components/types";
import {
  EMBEDDING_PROVIDERS_ADMIN_URL,
  LLM_PROVIDERS_ADMIN_URL,
} from "../../llm/constants";
import { mutate } from "swr";
import { PopupSpec, usePopup } from "@/components/admin/connectors/Popup";
import { Field } from "formik";

export function ChangeCredentialsModal({
  provider,
  onConfirm,
  onCancel,
  onDeleted,
  useFileUpload,
}: {
  provider: CloudEmbeddingProvider;
  onConfirm: () => void;
  onCancel: () => void;
  onDeleted: () => void;
  useFileUpload: boolean;
}) {
  const [apiKey, setApiKey] = useState("");
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
        `${EMBEDDING_PROVIDERS_ADMIN_URL}/${provider.name}`,
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

    try {
      const body = JSON.stringify({
        api_key: apiKey,
        provider: provider.name.toLowerCase().split(" ")[0],
        default_model_id: provider.name,
      });

      const testResponse = await fetch("/api/admin/embedding/test-embedding", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider: provider.name.toLowerCase().split(" ")[0],
          api_key: apiKey,
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
          name: provider.name,
          api_key: apiKey,
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

      onConfirm();
    } catch (error) {
      setTestError(
        error instanceof Error ? error.message : "An unknown error occurred"
      );
    }
  };

  return (
    <Modal
      icon={provider.icon}
      title={`Modify your ${provider.name} key`}
      onOutsideClick={onCancel}
    >
      <div className="mb-4">
        <Subtitle className="mt-4 font-bold text-lg mb-2">
          Want to swap out your key?
        </Subtitle>

        <div className="flex flex-col gap-y-2">
          {useFileUpload ? (
            <>
              <Label>Upload JSON File</Label>
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
              <div className="flex gap-x-2 items-center">
                <Label>New API Key</Label>
              </div>
              <input
                className={`
                    border 
                    border-border 
                    rounded 
                    w-full 
                    py-2 
                    px-3 
                    mt-1
                    bg-background-emphasis
                `}
                value={apiKey}
                onChange={(e: any) => setApiKey(e.target.value)}
                placeholder="Paste your API key here"
              />
            </>
          )}
          <a
            href={provider.apiLink}
            target="_blank"
            rel="noopener noreferrer"
            className="underline cursor-pointer"
          >
            Visit API
          </a>
        </div>

        {testError && (
          <Callout title="Error" color="red" className="mt-4">
            {testError}
          </Callout>
        )}

        <div className="flex mt-8 justify-between">
          <Button
            color="blue"
            onClick={() => handleSubmit()}
            disabled={!apiKey}
          >
            Execute Key Swap
          </Button>
        </div>
        <Divider />

        <Subtitle className="mt-4 font-bold text-lg mb-2">
          You can also delete your key.
        </Subtitle>
        <Text className="mb-2">
          This is only possible if you have already switched to a different
          embedding type!
        </Text>

        <Button onClick={handleDelete} color="red">
          Delete key
        </Button>
        {deletionError && (
          <Callout title="Error" color="red" className="mt-4">
            {deletionError}
          </Callout>
        )}
      </div>
    </Modal>
  );
}
