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
        `${EMBEDDING_PROVIDERS_ADMIN_URL}/${provider.provider_type}`,
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
      const testResponse = await fetch("/api/admin/embedding/test-embedding", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider_type: provider.provider_type.toLowerCase().split(" ")[0],
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
          provider_type: provider.provider_type.toLowerCase().split(" ")[0],
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
      width="max-w-3xl"
      icon={provider.icon}
      title={`Modify your ${provider.provider_type} key`}
      onOutsideClick={onCancel}
    >
      <div className="mb-4">
        <Subtitle className="font-bold text-lg">
          Want to swap out your key?
        </Subtitle>
        <a
          href={provider.apiLink}
          target="_blank"
          rel="noopener noreferrer"
          className="underline cursor-pointer mt-2 mb-4"
        >
          Visit API
        </a>

        <div className="flex flex-col mt-4 gap-y-2">
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
        </div>

        {testError && (
          <Callout title="Error" color="red" className="mt-4">
            {testError}
          </Callout>
        )}

        <div className="flex mt-4 justify-between">
          <Button
            color="blue"
            onClick={() => handleSubmit()}
            disabled={!apiKey}
          >
            Swap Key
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
