import { useTranslation } from "@/hooks/useTranslation";
import k from "./../../../../i18n/keys";
import React, { useRef, useState } from "react";
import Text from "@/components/ui/text";
import { Callout } from "@/components/ui/callout";
import { Button } from "@/components/ui/button";
import { Formik, Form } from "formik";
import * as Yup from "yup";
import { Label, TextFormField } from "@/components/admin/connectors/Field";
import { LoadingAnimation } from "@/components/Loading";
import {
  CloudEmbeddingProvider,
  EmbeddingProvider,
} from "../../../../components/embedding/interfaces";
import { EMBEDDING_PROVIDERS_ADMIN_URL } from "../../configuration/llm/constants";
import { Modal } from "@/components/Modal";

export function ProviderCreationModal({
  selectedProvider,
  onConfirm,
  onCancel,
  existingProvider,
  isProxy,
  isAzure,
  updateCurrentModel,
}: {
  updateCurrentModel: (
    newModel: string,
    provider_type: EmbeddingProvider
  ) => void;
  selectedProvider: CloudEmbeddingProvider;
  onConfirm: () => void;
  onCancel: () => void;
  existingProvider?: CloudEmbeddingProvider;
  isProxy?: boolean;
  isAzure?: boolean;
}) {
  const { t } = useTranslation();
  const useFileUpload = selectedProvider.provider_type == "Google";

  const [isProcessing, setIsProcessing] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string>("");
  const [fileName, setFileName] = useState<string>("");

  const initialValues = {
    provider_type:
      existingProvider?.provider_type || selectedProvider.provider_type,
    api_key: existingProvider?.api_key || "",
    api_url: existingProvider?.api_url || "",
    custom_config: existingProvider?.custom_config
      ? Object.entries(existingProvider.custom_config)
      : [],
    model_id: 0,
    model_name: null,
  };

  const validationSchema = Yup.object({
    provider_type: Yup.string().required(t(k.PROVIDER_TYPE_REQUIRED)),
    api_key:
      isProxy || isAzure
        ? Yup.string()
        : useFileUpload
        ? Yup.string()
        : Yup.string().required(t(k.API_KEY_REQUIRED)),
    model_name: isProxy
      ? Yup.string().required(t(k.MODEL_NAME_REQUIRED))
      : Yup.string().nullable(),
    api_url:
      isProxy || isAzure
        ? Yup.string().required(t(k.API_URL_REQUIRED))
        : Yup.string(),
    deployment_name: isAzure
      ? Yup.string().required(t(k.DEPLOYMENT_NAME_REQUIRED))
      : Yup.string(),
    api_version: isAzure
      ? Yup.string().required(t(k.API_VERSION_REQUIRED))
      : Yup.string(),
    custom_config: Yup.array().of(Yup.array().of(Yup.string()).length(2)),
  });

  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileUpload = async (
    event: React.ChangeEvent<HTMLInputElement>,
    setFieldValue: (field: string, value: any) => void
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
        } catch (parseError) {
          throw new Error(t(k.FAILED_TO_PARSE_JSON_FILE));
        }
        setFieldValue("api_key", JSON.stringify(jsonContent));
      } catch (error) {
        setFieldValue("api_key", "");
      }
    }
  };

  const handleSubmit = async (
    values: any,
    { setSubmitting }: { setSubmitting: (isSubmitting: boolean) => void }
  ) => {
    setIsProcessing(true);
    setErrorMsg("");
    try {
      const customConfig = Object.fromEntries(values.custom_config);
      const providerType = values.provider_type.toLowerCase().split(" ")[0];
      const isOpenAI = providerType === "openai";

      const testModelName =
        isOpenAI || isAzure ? "text-embedding-3-small" : values.model_name;

      const testEmbeddingPayload = {
        provider_type: providerType,
        api_key: values.api_key,
        api_url: values.api_url,
        model_name: testModelName,
        api_version: values.api_version,
        deployment_name: values.deployment_name,
      };

      const initialResponse = await fetch(
        "/api/admin/embedding/test-embedding",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(testEmbeddingPayload),
        }
      );

      if (!initialResponse.ok) {
        const errorMsg = (await initialResponse.json()).detail;
        setErrorMsg(errorMsg);
        setIsProcessing(false);
        setSubmitting(false);
        return;
      }

      const response = await fetch(EMBEDDING_PROVIDERS_ADMIN_URL, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...values,
          api_version: values.api_version,
          deployment_name: values.deployment_name,
          provider_type: values.provider_type.toLowerCase().split(" ")[0],
          custom_config: customConfig,
          is_default_provider: false,
          is_configured: true,
        }),
      });

      if (isAzure) {
        updateCurrentModel(values.model_name, EmbeddingProvider.AZURE);
      }

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || t(k.FAILED_TO_UPDATE_PROVIDER));
      }

      onConfirm();
    } catch (error: unknown) {
      if (error instanceof Error) {
        setErrorMsg(error.message);
      } else {
        setErrorMsg(t(k.UNKNOWN_ERROR_OCCURRED));
      }
    } finally {
      setIsProcessing(false);
      setSubmitting(false);
    }
  };

  return (
    <Modal
      title={`${t(k.CONFIGURE)} ${selectedProvider.provider_type}`}
      onOutsideClick={onCancel}
      icon={selectedProvider.icon}
    >
      <div>
        <Formik
          initialValues={initialValues}
          validationSchema={validationSchema}
          onSubmit={handleSubmit}
        >
          {({ isSubmitting, handleSubmit, setFieldValue }) => (
            <Form onSubmit={handleSubmit} className="space-y-4">
              <Text className="text-lg mb-2">
                {t(k.YOU_ARE_SETTING_THE_CREDENTIAL)}{" "}
                <a
                  className="cursor-pointer underline"
                  target="_blank"
                  href={selectedProvider.docsLink}
                  rel="noreferrer"
                >
                  {t(k.HERE)}
                </a>{" "}
                {t(k.AND_GATHER_YOUR)}{" "}
                <a
                  className="cursor-pointer underline"
                  target="_blank"
                  href={selectedProvider.apiLink}
                  rel="noreferrer"
                >
                  {isProxy || isAzure ? t(k.API_URL) : t(k.API_KEY1)}
                </a>
              </Text>

              <div className="flex w-full flex-col gap-y-6">
                {(isProxy || isAzure) && (
                  <TextFormField
                    name="api_url"
                    label="API URL"
                    placeholder="API URL"
                    type="text"
                  />
                )}

                {isProxy && (
                  <TextFormField
                    name="model_name"
                    label={`${t(k.MODEL_NAME)} ${
                      isProxy ? t(k.FOR_TESTING) : ""
                    }`}
                    placeholder={t(k.MODEL_NAME)}
                    type="text"
                  />
                )}

                {isAzure && (
                  <TextFormField
                    name="deployment_name"
                    label={t(k.DEPLOYMENT_NAME)}
                    placeholder={t(k.DEPLOYMENT_NAME)}
                    type="text"
                  />
                )}

                {isAzure && (
                  <TextFormField
                    name="api_version"
                    label={t(k.API_VERSION)}
                    placeholder={t(k.API_VERSION)}
                    type="text"
                  />
                )}

                {useFileUpload ? (
                  <>
                    <Label>{t(k.UPLOAD_JSON_FILE)}</Label>
                    <input
                      ref={fileInputRef}
                      type="file"
                      accept=".json"
                      onChange={(e) => handleFileUpload(e, setFieldValue)}
                      className="text-lg w-full p-1"
                    />

                    {fileName && (
                      <p>
                        {t(k.UPLOADED_FILE)} {fileName}
                      </p>
                    )}
                  </>
                ) : (
                  <TextFormField
                    name="api_key"
                    label={`${t(k.API_KEY)} ${
                      isProxy ? t(k.FOR_NON_LOCAL_DEPLOYMENTS) : ""
                    }`}
                    placeholder="API Key"
                    type="password"
                  />
                )}

                <a
                  href={selectedProvider.apiLink}
                  target="_blank"
                  className="underline cursor-pointer"
                  rel="noreferrer"
                >
                  {t(k.LEARN_MORE_HERE)}
                </a>
              </div>

              {errorMsg && (
                <Callout title={t(k.ERROR)} type="danger">
                  {errorMsg}
                </Callout>
              )}

              <Button
                type="submit"
                variant="submit"
                className="w-full"
                disabled={isSubmitting}
              >
                {isProcessing ? (
                  <LoadingAnimation />
                ) : existingProvider ? (
                  t(k.UPDATE)
                ) : (
                  t(k.CREATE1)
                )}
              </Button>
            </Form>
          )}
        </Formik>
      </div>
    </Modal>
  );
}
