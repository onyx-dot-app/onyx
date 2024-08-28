import React, { Dispatch, forwardRef, SetStateAction, useState } from "react";
import { Formik, Form, FormikProps } from "formik";
import * as Yup from "yup";
import { EditingValue } from "@/components/credentials/EditingValue";
import {
  RerankerProvider,
  RerankingDetails,
  rerankingModels,
} from "./interfaces";
import { FiExternalLink } from "react-icons/fi";
import { CohereIcon, MixedBreadIcon } from "@/components/icons/icons";
import { Modal } from "@/components/Modal";
import { Button } from "@tremor/react";

interface RerankingDetailsFormProps {
  setRerankingDetails: Dispatch<SetStateAction<RerankingDetails>>;
  currentRerankingDetails: RerankingDetails;
  originalRerankingDetails: RerankingDetails;
  modelTab: "open" | "cloud" | null;
  setModelTab: Dispatch<SetStateAction<"open" | "cloud" | null>>;
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
    },
    ref
  ) => {
    const [isApiKeyModalOpen, setIsApiKeyModalOpen] = useState(false);

    return (
      <div className="p-2 rounded-lg max-w-4xl mx-auto">
        <h2 className="text-2xl font-bold mb-4 text-text-800">
          Post-processing
        </h2>
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
              Current
            </button>
          )}
          <div
            className={`${originalRerankingDetails.rerank_model_name && "px-2 ml-2"}`}
          >
            <button
              onClick={() => setModelTab("cloud")}
              className={`mr-2 p-2 font-bold  ${
                modelTab == "cloud"
                  ? "rounded bg-background-900 text-text-100 underline"
                  : " hover:underline bg-background-100"
              }`}
            >
              Cloud-based
            </button>
          </div>

          <div className="px-2 ">
            <button
              onClick={() => setModelTab("open")}
              className={` mx-2 p-2 font-bold  ${
                modelTab == "open"
                  ? "rounded bg-background-900 text-text-100 underline"
                  : "hover:underline bg-background-100"
              }`}
            >
              Self-hosted
            </button>
          </div>
        </div>

        <Formik
          innerRef={ref}
          initialValues={currentRerankingDetails}
          validationSchema={Yup.object().shape({
            rerank_model_name: Yup.string().nullable(),
            provider_type: Yup.mixed<RerankerProvider>()
              .nullable()
              .oneOf(Object.values(RerankerProvider))
              .optional(),
            api_key: Yup.string().nullable(),
            num_rerank: Yup.number().min(1, "Must be at least 1"),
          })}
          onSubmit={async (_, { setSubmitting }) => {
            setSubmitting(false);
          }}
          enableReinitialize={true}
        >
          {({ values, setFieldValue }) => (
            <Form className="space-y-6">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {(modelTab
                  ? rerankingModels.filter(
                      (model) => model.cloud == (modelTab == "cloud")
                    )
                  : rerankingModels.filter(
                      (modelCard) =>
                        modelCard.modelName ==
                        originalRerankingDetails.rerank_model_name
                    )
                ).map((card) => {
                  const isSelected =
                    values.provider_type === card.provider &&
                    values.rerank_model_name === card.modelName;
                  return (
                    <div
                      key={`${card.provider}-${card.modelName}`}
                      className={`p-4 border rounded-lg cursor-pointer transition-all duration-200 ${
                        isSelected
                          ? "border-blue-500 bg-blue-50 shadow-md"
                          : "border-gray-200 hover:border-blue-300 hover:shadow-sm"
                      }`}
                      onClick={() => {
                        if (card.provider) {
                          setIsApiKeyModalOpen(true);
                        }
                        setRerankingDetails({
                          ...values,
                          provider_type: card.provider!,
                          rerank_model_name: card.modelName,
                        });
                        setFieldValue("provider_type", card.provider);
                        setFieldValue("rerank_model_name", card.modelName);
                      }}
                    >
                      <div className="flex items-center justify-between mb-3">
                        <div className="flex items-center">
                          {card.provider === RerankerProvider.COHERE ? (
                            <CohereIcon size={24} className="mr-2" />
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
                      <p className="text-sm text-gray-600 mb-2">
                        {card.description}
                      </p>
                      <div className="text-xs text-gray-500">
                        {card.cloud ? "Cloud-based" : "Self-hosted"}
                      </div>
                    </div>
                  );
                })}
              </div>

              {isApiKeyModalOpen && (
                <Modal
                  onOutsideClick={() => {
                    Object.keys(originalRerankingDetails).forEach((key) => {
                      setFieldValue(
                        key,
                        originalRerankingDetails[key as keyof RerankingDetails]
                      );
                    });

                    setIsApiKeyModalOpen(false);
                  }}
                  width="w-[800px]"
                  title="API Key Configuration"
                >
                  <div className="w-full px-4">
                    <EditingValue
                      optional={false}
                      currentValue={values.api_key}
                      onChange={(value: string | null) => {
                        setRerankingDetails({ ...values, api_key: value });
                        setFieldValue("api_key", value);
                      }}
                      setFieldValue={setFieldValue}
                      type="password"
                      label="Cohere API Key"
                      name="api_key"
                    />
                    <div className="mt-4 flex justify-between">
                      <Button
                        onClick={() => {
                          Object.keys(originalRerankingDetails).forEach(
                            (key) => {
                              setFieldValue(
                                key,
                                originalRerankingDetails[
                                  key as keyof RerankingDetails
                                ]
                              );
                            }
                          );

                          setIsApiKeyModalOpen(false);
                        }}
                        color="red"
                        size="xs"
                      >
                        Abandon
                      </Button>
                      <Button
                        onClick={() => setIsApiKeyModalOpen(false)}
                        color="blue"
                        size="xs"
                      >
                        Update
                      </Button>
                    </div>
                  </div>
                </Modal>
              )}
            </Form>
          )}
        </Formik>
      </div>
    );
  }
);

RerankingDetailsForm.displayName = "RerankingDetailsForm";
export default RerankingDetailsForm;
