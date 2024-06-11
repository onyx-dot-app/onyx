import { LoadingAnimation } from "@/components/Loading";
import { Button, Divider, Text } from "@tremor/react";
import {
  ArrayHelpers,
  ErrorMessage,
  Field,
  FieldArray,
  Form,
  Formik,
} from "formik";
import { FiPlus, FiTrash, FiX } from "react-icons/fi";
import { LLM_PROVIDERS_ADMIN_URL } from "./constants";
import {
  Label,
  SubLabel,
  TextArrayField,
  TextFormField,
} from "@/components/admin/connectors/Field";
import { useState } from "react";
import { useSWRConfig } from "swr";
import { FullLLMProvider } from "./interfaces";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import * as Yup from "yup";
import isEqual from "lodash/isEqual";

function customConfigProcessing(customConfigsList: [string, string][]) {
  const customConfig: { [key: string]: string } = {};
  customConfigsList.forEach(([key, value]) => {
    customConfig[key] = value;
  });
  return customConfig;
}

export function CustomLLMProviderUpdateForm({
  onClose,
  existingLlmProvider,
  shouldMarkAsDefault,
  setPopup,
}: {
  onClose: () => void;
  existingLlmProvider?: FullLLMProvider;
  shouldMarkAsDefault?: boolean;
  setPopup?: (popup: PopupSpec) => void;
}) {
  const { mutate } = useSWRConfig();

  const [isTesting, setIsTesting] = useState(false);
  const [testError, setTestError] = useState<string>("");

  // Define the initial values based on the provider's requirements
  const initialValues = {
    name: existingLlmProvider?.name ?? "",
    provider: existingLlmProvider?.provider ?? "",
    api_key: existingLlmProvider?.api_key ?? "",
    api_base: existingLlmProvider?.api_base ?? "",
    api_version: existingLlmProvider?.api_version ?? "",
    default_model_name: existingLlmProvider?.default_model_name ?? null,
    fast_default_model_name:
      existingLlmProvider?.fast_default_model_name ?? null,
    model_names: existingLlmProvider?.model_names ?? [],
    custom_config_list: existingLlmProvider?.custom_config
      ? Object.entries(existingLlmProvider.custom_config)
      : [],
  };

  // Setup validation schema if required
  const validationSchema = Yup.object({
    name: Yup.string().required("Display Name is required"),
    provider: Yup.string().required("Provider Name is required"),
    api_key: Yup.string(),
    api_base: Yup.string(),
    api_version: Yup.string(),
    model_names: Yup.array(Yup.string().required("Model name is required")),
    default_model_name: Yup.string().required("Model name is required"),
    fast_default_model_name: Yup.string().nullable(),
    custom_config_list: Yup.array(),
  });

  return (
    <Formik
      initialValues={initialValues}
      validationSchema={validationSchema}
      onSubmit={async (values, { setSubmitting }) => {
        setSubmitting(true);

        if (values.model_names.length === 0) {
          const fullErrorMsg = "At least one model name is required";
          if (setPopup) {
            setPopup({
              type: "error",
              message: fullErrorMsg,
            });
          } else {
            alert(fullErrorMsg);
          }
          setSubmitting(false);
          return;
        }

        // test the configuration
        if (!isEqual(values, initialValues)) {
          setIsTesting(true);

          const response = await fetch("/api/admin/llm/test", {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
            },
            body: JSON.stringify({
              custom_config: customConfigProcessing(values.custom_config_list),
              ...values,
            }),
          });
          setIsTesting(false);

          if (!response.ok) {
            const errorMsg = (await response.json()).detail;
            setTestError(errorMsg);
            return;
          }
        }

        const response = await fetch(LLM_PROVIDERS_ADMIN_URL, {
          method: "PUT",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            ...values,
            custom_config: customConfigProcessing(values.custom_config_list),
          }),
        });

        if (!response.ok) {
          const errorMsg = (await response.json()).detail;
          const fullErrorMsg = existingLlmProvider
            ? `Failed to update provider: ${errorMsg}`
            : `Failed to enable provider: ${errorMsg}`;
          if (setPopup) {
            setPopup({
              type: "error",
              message: fullErrorMsg,
            });
          } else {
            alert(fullErrorMsg);
          }
          return;
        }

        if (shouldMarkAsDefault) {
          const newLlmProvider = (await response.json()) as FullLLMProvider;
          const setDefaultResponse = await fetch(
            `${LLM_PROVIDERS_ADMIN_URL}/${newLlmProvider.id}/default`,
            {
              method: "POST",
            }
          );
          if (!setDefaultResponse.ok) {
            const errorMsg = (await setDefaultResponse.json()).detail;
            const fullErrorMsg = `Failed to set provider as default: ${errorMsg}`;
            if (setPopup) {
              setPopup({
                type: "error",
                message: fullErrorMsg,
              });
            } else {
              alert(fullErrorMsg);
            }
            return;
          }
        }

        mutate(LLM_PROVIDERS_ADMIN_URL);
        onClose();

        const successMsg = existingLlmProvider
          ? "Provider updated successfully!"
          : "Provider enabled successfully!";
        if (setPopup) {
          setPopup({
            type: "success",
            message: successMsg,
          });
        } else {
          alert(successMsg);
        }

        setSubmitting(false);
      }}
    >
      {({ values }) => (
        <Form>
          <TextFormField
            name="name"
            label="Display Name"
            subtext="A name which you can use to identify this provider when selecting it in the UI."
            placeholder="Display Name"
          />

          <Divider />

          <TextFormField
            name="provider"
            label="Provider Name"
            subtext={
              <>
                Should be one of the providers listed at{" "}
                <a
                  target="_blank"
                  href="https://docs.litellm.ai/docs/providers"
                  className="text-link"
                >
                  https://docs.litellm.ai/docs/providers
                </a>
                .
              </>
            }
            placeholder="Name of the custom provider"
          />

          <Divider />

          <SubLabel>
            Fill in the following as is needed. Refer to the LiteLLM
            documentation for the model provider name specified above in order
            to determine which fields are required.
          </SubLabel>

          <TextFormField
            name="api_key"
            label="[Optional] API Key"
            placeholder="API Key"
            type="password"
          />

          <TextFormField
            name="api_base"
            label="[Optional] API Base"
            placeholder="API Base"
          />

          <TextFormField
            name="api_version"
            label="[Optional] API Version"
            placeholder="API Version"
          />

          <Label>[Optional] Custom Configs</Label>
          <SubLabel>
            <>
              <div>
                Additional configurations needed by the model provider. Are
                passed to litellm via environment variables.
              </div>

              <div className="mt-2">
                For example, when configuring the Cloudflare provider, you would
                need to set `CLOUDFLARE_ACCOUNT_ID` as the key and your
                Cloudflare account ID as the value.
              </div>
            </>
          </SubLabel>

          <FieldArray
            name="custom_config_list"
            render={(arrayHelpers: ArrayHelpers<any[]>) => (
              <div>
                {values.custom_config_list.map((_, index) => {
                  return (
                    <div key={index} className={index === 0 ? "mt-2" : "mt-6"}>
                      <div className="flex">
                        <div className="w-full mr-6 border border-border p-3 rounded">
                          <div>
                            <Label>Key</Label>
                            <Field
                              name={`custom_config_list[${index}][0]`}
                              className={`
                                  border 
                                  border-border 
                                  bg-background 
                                  rounded 
                                  w-full 
                                  py-2 
                                  px-3 
                                  mr-4
                                `}
                              autoComplete="off"
                            />
                            <ErrorMessage
                              name={`custom_config_list[${index}][0]`}
                              component="div"
                              className="text-error text-sm mt-1"
                            />
                          </div>

                          <div className="mt-3">
                            <Label>Value</Label>
                            <Field
                              name={`custom_config_list[${index}][1]`}
                              className={`
                                  border 
                                  border-border 
                                  bg-background 
                                  rounded 
                                  w-full 
                                  py-2 
                                  px-3 
                                  mr-4
                                `}
                              autoComplete="off"
                            />
                            <ErrorMessage
                              name={`custom_config_list[${index}][1]`}
                              component="div"
                              className="text-error text-sm mt-1"
                            />
                          </div>
                        </div>
                        <div className="my-auto">
                          <FiX
                            className="my-auto w-10 h-10 cursor-pointer hover:bg-hover rounded p-2"
                            onClick={() => arrayHelpers.remove(index)}
                          />
                        </div>
                      </div>
                    </div>
                  );
                })}

                <Button
                  onClick={() => {
                    arrayHelpers.push(["", ""]);
                  }}
                  className="mt-3"
                  color="green"
                  size="xs"
                  type="button"
                  icon={FiPlus}
                >
                  Add New
                </Button>
              </div>
            )}
          />

          <Divider />

          <TextArrayField
            name="model_names"
            label="Model Names"
            values={values}
            subtext={`List the individual models that you want to make 
            available as a part of this provider. At least one must be specified. 
            As an example, for OpenAI one model might be "gpt-4".`}
          />

          <Divider />

          <TextFormField
            name="default_model_name"
            subtext={`
              The model to use by default for this provider unless 
              otherwise specified. Must be one of the models listed 
              above.`}
            label="Default Model"
            placeholder="E.g. gpt-4"
          />

          <TextFormField
            name="fast_default_model_name"
            subtext={`The model to use for lighter flows like \`LLM Chunk Filter\` 
                for this provider. If not set, will use 
                the Default Model configured above.`}
            label="[Optional] Fast Model"
            placeholder="E.g. gpt-4"
          />

          <Divider />

          <div>
            {/* NOTE: this is above the test button to make sure it's visible */}
            {testError && <Text className="text-error mt-2">{testError}</Text>}

            <div className="flex w-full mt-4">
              <Button type="submit" size="xs">
                {isTesting ? (
                  <LoadingAnimation text="Testing" />
                ) : existingLlmProvider ? (
                  "Update"
                ) : (
                  "Enable"
                )}
              </Button>
              {existingLlmProvider && (
                <Button
                  type="button"
                  color="red"
                  className="ml-3"
                  size="xs"
                  icon={FiTrash}
                  onClick={async () => {
                    const response = await fetch(
                      `${LLM_PROVIDERS_ADMIN_URL}/${existingLlmProvider.id}`,
                      {
                        method: "DELETE",
                      }
                    );
                    if (!response.ok) {
                      const errorMsg = (await response.json()).detail;
                      alert(`Failed to delete provider: ${errorMsg}`);
                      return;
                    }

                    mutate(LLM_PROVIDERS_ADMIN_URL);
                    onClose();
                  }}
                >
                  Delete
                </Button>
              )}
            </div>
          </div>
        </Form>
      )}
    </Formik>
  );
}
