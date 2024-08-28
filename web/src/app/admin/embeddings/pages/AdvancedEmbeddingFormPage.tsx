import React, { Dispatch, forwardRef, SetStateAction } from "react";
import { Formik, Form, FormikProps, FieldArray, Field } from "formik";
import * as Yup from "yup";
import { EditingValue } from "@/components/credentials/EditingValue";
import CredentialSubText from "@/components/credentials/CredentialFields";
import { TrashIcon } from "@/components/icons/icons";
import { FaPlus } from "react-icons/fa";
import { AdvancedDetails, RerankingDetails } from "../interfaces";

interface AdvancedEmbeddingFormPageProps {
  updateAdvancedEmbeddingDetails: (
    key: keyof AdvancedDetails,
    value: any
  ) => void;
  advancedEmbeddingDetails: AdvancedDetails;
  setRerankingDetails: Dispatch<SetStateAction<RerankingDetails>>;
  numRerank: number;
}

const AdvancedEmbeddingFormPage = forwardRef<
  FormikProps<any>,
  AdvancedEmbeddingFormPageProps
>(
  (
    {
      updateAdvancedEmbeddingDetails,
      advancedEmbeddingDetails,
      setRerankingDetails,
      numRerank,
    },
    ref
  ) => {
    return (
      <div className="py-4 rounded-lg max-w-4xl px-4 mx-auto">
        <h2 className="text-2xl font-bold mb-4 text-text-800">
          Advanced Configuration
        </h2>
        <Formik
          innerRef={ref}
          initialValues={{
            multilingual_expansion:
              advancedEmbeddingDetails.multilingual_expansion,
            multipass_indexing: advancedEmbeddingDetails.multipass_indexing,
            disable_rerank_for_streaming:
              advancedEmbeddingDetails.disable_rerank_for_streaming,
            num_rerank: numRerank,
          }}
          validationSchema={Yup.object().shape({
            multilingual_expansion: Yup.array().of(Yup.string()),
            multipass_indexing: Yup.boolean(),
            disable_rerank_for_streaming: Yup.boolean(),
          })}
          onSubmit={async (_, { setSubmitting }) => {
            setSubmitting(false);
          }}
          enableReinitialize={true}
        >
          {({ values, setFieldValue }) => (
            <Form className="space-y-6">
              <FieldArray name="multilingual_expansion">
                {({ push, remove }) => (
                  <div>
                    <label
                      htmlFor="multilingual_expansion"
                      className="block text-sm font-medium text-text-700 mb-1"
                    >
                      Multilingual Expansion
                      <span className="text-text-500 ml-1">(optional)</span>
                    </label>
                    <CredentialSubText>
                      List of languages for multilingual expansion. Leave empty
                      for no additional expansion.
                    </CredentialSubText>
                    {values.multilingual_expansion.map(
                      (_: any, index: number) => (
                        <div key={index} className="w-full flex mb-4">
                          <Field
                            name={`multilingual_expansion.${index}`}
                            className={`w-full bg-input text-sm p-2  border border-border-medium rounded-md
                                      focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 mr-2`}
                            onChange={(
                              e: React.ChangeEvent<HTMLInputElement>
                            ) => {
                              const newValue = [
                                ...values.multilingual_expansion,
                              ];
                              newValue[index] = e.target.value;
                              setFieldValue("multilingual_expansion", newValue);
                              updateAdvancedEmbeddingDetails(
                                "multilingual_expansion",
                                newValue
                              );
                            }}
                            value={values.multilingual_expansion[index]}
                          />

                          <button
                            type="button"
                            onClick={() => {
                              remove(index);
                              const newValue =
                                values.multilingual_expansion.filter(
                                  (_: any, i: number) => i !== index
                                );
                              setFieldValue("multilingual_expansion", newValue);
                              updateAdvancedEmbeddingDetails(
                                "multilingual_expansion",
                                newValue
                              );
                            }}
                            className={`p-2 my-auto bg-input flex-none rounded-md 
                              bg-red-500 text-white hover:bg-red-600
                              focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-opacity-50`}
                          >
                            <TrashIcon className="text-white my-auto" />
                          </button>
                        </div>
                      )
                    )}

                    <button
                      type="button"
                      onClick={() => push("")}
                      className={`mt-2 p-2 bg-rose-500 text-xs text-white rounded-md flex items-center
                        hover:bg-rose-600 focus:outline-none focus:ring-2 focus:ring-rose-500 focus:ring-opacity-50`}
                    >
                      <FaPlus className="mr-2" />
                      Add Language
                    </button>
                  </div>
                )}
              </FieldArray>

              <div key="multipass_indexing">
                <EditingValue
                  description="Enable multipass indexing for both mini and large chunks."
                  optional
                  currentValue={values.multipass_indexing}
                  onChangeBool={(value: boolean) => {
                    updateAdvancedEmbeddingDetails("multipass_indexing", value);
                    setFieldValue("multipass_indexing", value);
                  }}
                  setFieldValue={setFieldValue}
                  type="checkbox"
                  label="Multipass Indexing"
                  name="multipassIndexing"
                />
              </div>
              <div key="disable_rerank_for_streaming">
                <EditingValue
                  description="Disable reranking for streaming to improve response time."
                  optional
                  currentValue={values.disable_rerank_for_streaming}
                  onChangeBool={(value: boolean) => {
                    updateAdvancedEmbeddingDetails(
                      "disable_rerank_for_streaming",
                      value
                    );
                    setFieldValue("disable_rerank_for_streaming", value);
                  }}
                  setFieldValue={setFieldValue}
                  type="checkbox"
                  label="Disable Rerank for Streaming"
                  name="disableRerankForStreaming"
                />
              </div>
              <div key="num_rerank">
                <EditingValue
                  description="Number of results to rerank"
                  optional={false}
                  currentValue={values.num_rerank}
                  onChangeNumber={(value: number) => {
                    setRerankingDetails({ ...values, num_rerank: value });
                    setFieldValue("num_rerank", value);
                  }}
                  setFieldValue={setFieldValue}
                  type="number"
                  label="Number of Results to Rerank"
                  name="num_rerank"
                />
              </div>
            </Form>
          )}
        </Formik>
      </div>
    );
  }
);

AdvancedEmbeddingFormPage.displayName = "AdvancedEmbeddingFormPage";
export default AdvancedEmbeddingFormPage;
