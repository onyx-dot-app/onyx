import i18n from "@/i18n/init";
import k from "./../../../../i18n/keys";
import React, { useRef, useState } from "react";
import { Modal } from "@/components/Modal";
import { Callout } from "@/components/ui/callout";
import Text from "@/components/ui/text";
import { Separator } from "@/components/ui/separator";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/admin/connectors/Field";
import { CloudEmbeddingProvider } from "../../../../components/embedding/interfaces";
import {
  EMBEDDING_PROVIDERS_ADMIN_URL,
  LLM_PROVIDERS_ADMIN_URL,
} from "../../configuration/llm/constants";
import { mutate } from "swr";
import { testEmbedding } from "../pages/utils";

export function ChangeCredentialsModal({
  provider,
  onConfirm,
  onCancel,
  onDeleted,
  useFileUpload,
  isProxy = false,
  isAzure = false,
}: {
  provider: CloudEmbeddingProvider;
  onConfirm: () => void;
  onCancel: () => void;
  onDeleted: () => void;
  useFileUpload: boolean;
  isProxy?: boolean;
  isAzure?: boolean;
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
      fileInputRef.current.value = i18n.t(k._1);
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
          throw new Error(i18n.t(k.FAILED_TO_PARSE_JSON_FILE));
        }
      } catch (error) {
        setTestError(
          error instanceof Error
            ? error.message
            : i18n.t(k.UNKNOWN_ERROR_PROCESSING_FILE)
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
        error instanceof Error
          ? error.message
          : i18n.t(k.UNKNOWN_ERROR_OCCURRED)
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
            `${i18n.t(k.FAILED_TO_UPDATE_PROVIDER_CHECK_API)} ${
              isProxy ? "API URL" : "API key"
            }`
        );
      }

      onConfirm();
    } catch (error) {
      setTestError(
        error instanceof Error
          ? error.message
          : i18n.t(k.UNKNOWN_ERROR_OCCURRED)
      );
    }
  };
  return (
    <Modal
      width="max-w-3xl"
      icon={provider.icon}
      title={`${i18n.t(k.MODIFY_YOUR)} ${provider.provider_type} ${
        isProxy ? i18n.t(k.CONFIGURATION) : i18n.t(k.KEY)
      }`}
      onOutsideClick={onCancel}
    >
      <>
        {!isAzure && (
          <>
            <p className="mb-4">
              {i18n.t(k.YOU_CAN_MODIFY_YOUR_CONFIGURAT)}
              {isProxy ? i18n.t(k.OR_API_URL) : i18n.t(k._8)}
            </p>

            <div className="mb-4 flex flex-col gap-y-2">
              <Label className="mt-2">{i18n.t(k.API_KEY)}</Label>
              {useFileUpload ? (
                <>
                  <Label className="mt-2">{i18n.t(k.UPLOAD_JSON_FILE)}</Label>
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept=".json"
                    onChange={handleFileUpload}
                    className="text-lg w-full p-1"
                  />

                  {fileName && (
                    <p>
                      {i18n.t(k.UPLOADED_FILE)} {fileName}
                    </p>
                  )}
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
                    placeholder={i18n.t(k.PASTE_YOUR_API_KEY_HERE)}
                  />
                </>
              )}

              {isProxy && (
                <>
                  <Label className="mt-2">{i18n.t(k.API_URL)}</Label>

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
                    placeholder={i18n.t(k.PASTE_YOUR_API_URL_HERE)}
                  />

                  {deletionError && (
                    <Callout
                      type="danger"
                      title={i18n.t(k.ERROR_TITLE)}
                      className="mt-4"
                    >
                      {deletionError}
                    </Callout>
                  )}

                  <div>
                    <Label className="mt-2">{i18n.t(k.TEST_MODEL)}</Label>
                    <p>{i18n.t(k.SINCE_YOU_ARE_USING_A_LITELLM)}</p>
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
                    placeholder={i18n.t(k.PASTE_YOUR_MODEL_NAME_HERE)}
                  />
                </>
              )}

              {testError && (
                <Callout
                  type="danger"
                  title={i18n.t(k.ERROR_TITLE)}
                  className="my-4"
                >
                  {testError}
                </Callout>
              )}

              <Button
                className="mr-auto mt-4"
                variant="submit"
                onClick={() => handleSubmit()}
                disabled={!apiKey}
              >
                {i18n.t(k.UPDATE_CONFIGURATION)}
              </Button>

              <Separator />
            </div>
          </>
        )}

        <Text className="mt-4 font-bold text-lg mb-2">
          {i18n.t(k.YOU_CAN_DELETE_YOUR_CONFIGURAT)}
        </Text>
        <Text className="mb-2">{i18n.t(k.THIS_IS_ONLY_POSSIBLE_IF_YOU_H)}</Text>

        <Button
          className="mr-auto"
          onClick={handleDelete}
          variant="destructive"
        >
          {i18n.t(k.DELETE_CONFIGURATION)}
        </Button>
        {deletionError && (
          <Callout type="danger" title={i18n.t(k.ERROR_TITLE)} className="mt-4">
            {deletionError}
          </Callout>
        )}
      </>
    </Modal>
  );
}
