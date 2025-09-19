"use client";

import { useTranslation } from "@/hooks/useTranslation";
import k from "@/i18n/keys";
import React, {
  Dispatch,
  forwardRef,
  SetStateAction,
  useContext,
  useState,
} from "react";
import { Formik, Form, FormikProps } from "formik";
import * as Yup from "yup";
import {
  RerankerProvider,
  RerankingDetails,
  RerankingModel,
  rerankingModels,
} from "./interfaces";
import { FiExternalLink } from "react-icons/fi";
import {
  AmazonIcon,
  CohereIcon,
  LiteLLMIcon,
  MixedBreadIcon,
} from "@/components/icons/icons";
import { Modal } from "@/components/Modal";
import { Button } from "@/components/ui/button";
import { TextFormField } from "@/components/admin/connectors/Field";
import { SettingsContext } from "@/components/settings/SettingsProvider";

interface RerankingDetailsFormProps {
  setRerankingDetails: Dispatch<SetStateAction<RerankingDetails>>;
  currentRerankingDetails: RerankingDetails;
  originalRerankingDetails: RerankingDetails;
  modelTab: "open" | "cloud" | null;
  setModelTab: Dispatch<SetStateAction<"open" | "cloud" | null>>;
  onValidationChange?: (
    isValid: boolean,
    errors: Record<string, string>
  ) => void;
}

const RerankingDetailsForm = forwardRef<
  FormikProps<RerankingDetails>,
  RerankingDetailsFormProps
>(
  (
    {
      setRerankingDetails,
      originalRerankingDetails,
      currentRerankingDetails,
      modelTab,
      setModelTab,
      onValidationChange,
    },
    ref
  ) => {
    const { t } = useTranslation();
    const [showGpuWarningModalModel, setShowGpuWarningModalModel] =
      useState<RerankingModel | null>(null);
    const [isApiKeyModalOpen, setIsApiKeyModalOpen] = useState(false);
    const [showLiteLLMConfigurationModal, setShowLiteLLMConfigurationModal] =
      useState(false);

    const combinedSettings = useContext(SettingsContext);
    const gpuEnabled = combinedSettings?.settings.gpu_enabled;

    // Define the validation schema
    const validationSchema = Yup.object().shape({
      rerank_model_name: Yup.string().nullable(),
      rerank_provider_type: Yup.mixed<RerankerProvider>()
        .nullable()
        .oneOf(Object.values(RerankerProvider))
        .optional(),
      rerank_api_key: Yup.string()
        .nullable()
        .test(
          "required-if-cohere",
          t(k.COHERE_API_KEY_REQUIRED),
          function (value) {
            const { rerank_provider_type } = this.parent;
            return (
              rerank_provider_type === RerankerProvider.LITELLM ||
              (value !== null && value !== "")
            );
          }
        ),
      rerank_api_url: Yup.string()
        .url(t(k.VALID_URL_REQUIRED))
        .matches(/^https?:\/\//, t(k.URL_MUST_START_HTTP))
        .nullable()
        .test(
          "required-if-litellm",
          t(k.LITELLM_API_URL_REQUIRED),
          function (value) {
            const { rerank_provider_type } = this.parent;
            return (
              rerank_provider_type !== RerankerProvider.LITELLM ||
              (value !== null && value !== "")
            );
          }
        ),
    });

    return (
      <Formik
        innerRef={ref}
        initialValues={currentRerankingDetails}
        validationSchema={validationSchema}
        onSubmit={async (_, { setSubmitting }) => {
          setSubmitting(false);
        }}
        validate={(values) => {
          // Update parent component with values
          setRerankingDetails(values);

          // Run validation and report errors
          if (onValidationChange) {
            // We'll return an empty object here since Yup will handle the actual validation
            // But we need to check if there are any validation errors
            const errors: Record<string, string> = {};
            try {
              // Manually validate against the schema
              validationSchema.validateSync(values, { abortEarly: false });
              onValidationChange(true, {});
            } catch (validationError) {
              if (validationError instanceof Yup.ValidationError) {
                validationError.inner.forEach((err) => {
                  if (err.path) {
                    errors[err.path] = err.message;
                  }
                });
                onValidationChange(false, errors);
              }
            }
          }

          return {}; // Return empty object as Formik will handle the errors
        }}
        enableReinitialize={true}
      >
        {({ values, setFieldValue, resetForm }) => {
          const resetRerankingValues = () => {
            setRerankingDetails({
              rerank_api_key: null,
              rerank_provider_type: null,
              rerank_model_name: null,
              rerank_api_url: null,
            });
            resetForm();
          };

          return (
            <div className="p-2 rounded-lg max-w-4xl mx-auto">
              <p className="mb-4">{t(k.SELECT_FROM_CLOUD_SELF_HOSTED1)}</p>
              <div className="text-sm mr-auto mb-6 divide-x-2 flex">
                {originalRerankingDetails.rerank_model_name && (
                  <button
                    onClick={() => setModelTab(null)}
                    className={`mx-2 p-2 font-bold  ${
                      !modelTab
                        ? "rounded bg-background-900 text-text-100 underline"
                        : " hover:underline bg-background-100"
                    }`}
                  >
                    {t(k.CURRENT)}
                  </button>
                )}
                <div
                  className={`${
                    originalRerankingDetails.rerank_model_name && "px-2 ml-2"
                  }`}
                >
                  <button
                    onClick={() => setModelTab("cloud")}
                    className={`mr-2 p-2 font-bold  ${
                      modelTab == "cloud"
                        ? "rounded bg-neutral-900 dark:bg-neutral-950 text-neutral-100 dark:text-neutral-300 underline"
                        : " hover:underline bg-neutral-100 dark:bg-neutral-900"
                    }`}
                  >
                    {t(k.CLOUD_BASED)}
                  </button>
                </div>

                <div className="px-2">
                  <button
                    onClick={() => setModelTab("open")}
                    className={` mx-2 p-2 font-bold  ${
                      modelTab == "open"
                        ? "rounded bg-neutral-900 dark:bg-neutral-950 text-neutral-100 dark:text-neutral-300 underline"
                        : "hover:underline bg-neutral-100 dark:bg-neutral-900"
                    }`}
                  >
                    {t(k.SELF_HOSTED)}
                  </button>
                </div>
                {values.rerank_model_name && (
                  <div className="px-2">
                    <button
                      onClick={() => resetRerankingValues()}
                      className={`mx-2 p-2 font-bold rounded bg-neutral-100 dark:bg-neutral-900 text-neutral-900 dark:text-neutral-100 hover:underline`}
                    >
                      {t(k.REMOVE_RERANKING)}
                    </button>
                  </div>
                )}
              </div>

              <Form>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {(modelTab
                    ? rerankingModels.filter(
                        (model) => model.cloud == (modelTab == "cloud")
                      )
                    : rerankingModels.filter(
                        (modelCard) =>
                          (modelCard.modelName ==
                            originalRerankingDetails.rerank_model_name &&
                            modelCard.rerank_provider_type ==
                              originalRerankingDetails.rerank_provider_type) ||
                          (modelCard.rerank_provider_type ==
                            RerankerProvider.LITELLM &&
                            originalRerankingDetails.rerank_provider_type ==
                              RerankerProvider.LITELLM)
                      )
                  ).map((card) => {
                    const isSelected =
                      values.rerank_provider_type ===
                        card.rerank_provider_type &&
                      (card.modelName == null ||
                        values.rerank_model_name === card.modelName);

                    return (
                      <div
                        key={`${card.rerank_provider_type}-${card.modelName}`}
                        className={`p-4 border rounded-lg cursor-pointer transition-all duration-200 ${
                          isSelected
                            ? "border-blue-800 bg-blue-50 dark:bg-blue-950 dark:border-blue-700 shadow-md"
                            : "border-background-200 hover:border-blue-300 hover:shadow-sm dark:border-neutral-700 dark:hover:border-blue-300"
                        }`}
                        onClick={() => {
                          if (
                            card.rerank_provider_type == RerankerProvider.COHERE
                          ) {
                            setIsApiKeyModalOpen(true);
                          } else if (
                            card.rerank_provider_type ==
                            RerankerProvider.BEDROCK
                          ) {
                            setIsApiKeyModalOpen(true);
                          } else if (
                            card.rerank_provider_type ==
                            RerankerProvider.LITELLM
                          ) {
                            setShowLiteLLMConfigurationModal(true);
                          } else if (
                            !card.rerank_provider_type &&
                            !gpuEnabled
                          ) {
                            setShowGpuWarningModalModel(card);
                          }

                          if (!isSelected) {
                            setRerankingDetails({
                              ...values,
                              rerank_provider_type: card.rerank_provider_type!,
                              rerank_model_name: card.modelName || null,
                              rerank_api_key: null,
                              rerank_api_url: null,
                            });
                            setFieldValue(
                              "rerank_provider_type",
                              card.rerank_provider_type
                            );
                            setFieldValue("rerank_model_name", card.modelName);
                          }
                        }}
                      >
                        <div className="flex items-center justify-between mb-3">
                          <div className="flex items-center">
                            {card.rerank_provider_type ===
                            RerankerProvider.LITELLM ? (
                              <LiteLLMIcon size={24} className="mr-2" />
                            ) : card.rerank_provider_type ===
                              RerankerProvider.COHERE ? (
                              <CohereIcon size={24} className="mr-2" />
                            ) : card.rerank_provider_type ===
                              RerankerProvider.BEDROCK ? (
                              <AmazonIcon size={24} className="mr-2" />
                            ) : (
                              <MixedBreadIcon size={24} className="mr-2" />
                            )}
                            <h3 className="font-bold text-lg">
                              {card.displayName}
                            </h3>
                          </div>
                          {card.link && (
                            <a
                              href={card.link}
                              target="_blank"
                              rel="noopener noreferrer"
                              onClick={(e) => e.stopPropagation()}
                              className="text-blue-500 hover:text-blue-700 transition-colors duration-200"
                            >
                              <FiExternalLink size={18} />
                            </a>
                          )}
                        </div>
                        <p className="text-sm text-text-600 mb-2">
                          {card.description}
                        </p>
                        <div className="text-xs text-text-500">
                          {card.cloud ? t(k.CLOUD_BASED) : t(k.SELF_HOSTED)}
                        </div>
                      </div>
                    );
                  })}
                </div>

                {showGpuWarningModalModel && (
                  <Modal
                    onOutsideClick={() => setShowGpuWarningModalModel(null)}
                    width="w-[500px] flex flex-col"
                    title={t(k.GPU_NOT_ENABLED)}
                  >
                    <>
                      <p className="text-error font-semibold">
                        {t(k.WARNING2)}
                      </p>
                      <p>{t(k.LOCAL_RERANKING_MODELS_REQUIRE)}</p>
                      <div className="flex justify-end">
                        <Button
                          onClick={() => setShowGpuWarningModalModel(null)}
                          variant="submit"
                        >
                          {t(k.UNDERSTOOD)}
                        </Button>
                      </div>
                    </>
                  </Modal>
                )}
                {showLiteLLMConfigurationModal && (
                  <Modal
                    onOutsideClick={() => {
                      resetForm();
                      setShowLiteLLMConfigurationModal(false);
                    }}
                    width="w-[800px]"
                    title={t(k.API_KEY_CONFIGURATION)}
                  >
                    <div className="w-full  flex flex-col gap-y-4 px-4">
                      <TextFormField
                        subtext="Set the URL at which your LiteLLM Proxy is hosted"
                        placeholder={values.rerank_api_url || undefined}
                        onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                          const value = e.target.value;
                          setRerankingDetails({
                            ...values,
                            rerank_api_url: value,
                          });
                          setFieldValue("rerank_api_url", value);
                        }}
                        type="text"
                        label={t(k.LITELLM_PROXY_URL)}
                        name="rerank_api_url"
                      />

                      <TextFormField
                        subtext={t(k.SET_ACCESS_KEY_FOR_LITELLM)}
                        placeholder={
                          values.rerank_api_key
                            ? t(k._28).repeat(values.rerank_api_key.length)
                            : undefined
                        }
                        onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                          const value = e.target.value;
                          setRerankingDetails({
                            ...values,
                            rerank_api_key: value,
                          });
                          setFieldValue("rerank_api_key", value);
                        }}
                        type="password"
                        label={t(k.LITELLM_PROXY_KEY)}
                        name="rerank_api_key"
                        optional
                      />

                      <TextFormField
                        subtext={t(k.SET_MODEL_NAME_FOR_LITELLM)}
                        placeholder={
                          values.rerank_model_name
                            ? t(k._28).repeat(values.rerank_model_name.length)
                            : undefined
                        }
                        onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                          const value = e.target.value;
                          setRerankingDetails({
                            ...values,
                            rerank_model_name: value,
                          });
                          setFieldValue("rerank_model_name", value);
                        }}
                        label={t(k.LITELLM_MODEL_NAME)}
                        name="rerank_model_name"
                        optional
                      />

                      <div className="flex w-full justify-end mt-4">
                        <Button
                          onClick={() => {
                            setShowLiteLLMConfigurationModal(false);
                          }}
                          variant="submit"
                        >
                          {t(k.UPDATE)}
                        </Button>
                      </div>
                    </div>
                  </Modal>
                )}

                {isApiKeyModalOpen && (
                  <Modal
                    onOutsideClick={() => {
                      Object.keys(originalRerankingDetails).forEach((key) => {
                        setFieldValue(
                          key,
                          originalRerankingDetails[
                            key as keyof RerankingDetails
                          ]
                        );
                      });

                      setIsApiKeyModalOpen(false);
                    }}
                    width="w-[800px]"
                    title={t(k.API_KEY_CONFIGURATION)}
                  >
                    <div className="w-full px-4">
                      <TextFormField
                        placeholder={
                          values.rerank_api_key
                            ? t(k._28).repeat(values.rerank_api_key.length)
                            : values.rerank_provider_type ===
                              RerankerProvider.BEDROCK
                            ? t(k.AWS_ACCESSKEY_SECRETKEY_REGION)
                            : t(k.ENTER_YOUR_API_KEY)
                        }
                        onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                          const value = e.target.value;
                          setRerankingDetails({
                            ...values,
                            rerank_api_key: value,
                          });
                          setFieldValue("rerank_api_key", value);
                        }}
                        type="password"
                        label={
                          values.rerank_provider_type ===
                          RerankerProvider.BEDROCK
                            ? t(k.AWS_CREDENTIALS_IN_FORMAT_AWS)
                            : t(k.COHERE_API_KEY)
                        }
                        name="rerank_api_key"
                      />

                      <div className="flex w-full justify-end mt-4">
                        <Button
                          onClick={() => setIsApiKeyModalOpen(false)}
                          variant="submit"
                        >
                          {t(k.UPDATE)}
                        </Button>
                      </div>
                    </div>
                  </Modal>
                )}
              </Form>
            </div>
          );
        }}
      </Formik>
    );
  }
);

RerankingDetailsForm.displayName = "RerankingDetailsForm";
export default RerankingDetailsForm;
