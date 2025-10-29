import React, { useMemo, useState } from "react";
import Modal from "@/refresh-components/modals/Modal";
import {
  ModalIds,
  useChatModal,
} from "@/refresh-components/contexts/ChatModalContext";
import { WellKnownLLMProviderDescriptor } from "@/app/admin/configuration/llm/interfaces";
import { Form, Formik } from "formik";
import type { FormikProps } from "formik";
import { FormField } from "@/refresh-components/form/FormField";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import PasswordInputTypeIn from "@/refresh-components/inputs/PasswordInputTypeIn";
import { FormikField } from "@/refresh-components/form/FormikField";
import { Separator } from "@/components/ui/separator";
import { APIFormFieldState } from "@/refresh-components/form/types";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import Button from "@/refresh-components/buttons/Button";
import { MODAL_CONTENT_MAP } from "../constants";
import { LLM_PROVIDERS_ADMIN_URL } from "@/app/admin/configuration/llm/constants";

type LLMConnectionModalData = {
  icon: React.ReactNode;
  title: string;
  llmDescriptor: WellKnownLLMProviderDescriptor;
};

const LLMConnectionModal = () => {
  const { getModalData, toggleModal } = useChatModal();
  const data = getModalData<LLMConnectionModalData>();
  const icon = data?.icon;
  const title = data?.title ?? "";
  const llmDescriptor = data?.llmDescriptor;
  const modalContent = llmDescriptor
    ? MODAL_CONTENT_MAP[llmDescriptor.name]
    : undefined;
  const modelOptions = useMemo(
    () =>
      llmDescriptor
        ? llmDescriptor.model_configurations.map((model) => ({
            label: model.name,
            value: model.name,
          }))
        : [],
    [llmDescriptor]
  );

  const initialValues = useMemo(
    () => ({
      api_base: "",
      default_model_name: llmDescriptor?.default_model ?? "",
      api_key: "",
      api_key_changed: true,
      api_version: "",
      custom_config: {},
      deployment_name: "",
      fast_default_model_name:
        llmDescriptor?.default_fast_model ?? llmDescriptor?.default_model ?? "",
      name: "Default",
      provider: llmDescriptor?.name ?? "",
      model_configurations:
        llmDescriptor?.model_configurations.map((model) => ({
          name: model.name,
          is_visible: true,
          max_input_tokens: model.max_input_tokens,
          supports_image_input: model.supports_image_input,
        })) ?? [],
      groups: [],
      is_public: true,
    }),
    [llmDescriptor]
  );

  const [apiStatus, setApiStatus] = useState<APIFormFieldState>("loading");
  const [showApiMessage, setShowApiMessage] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string>("");
  const isApiError = apiStatus === "error";

  const testApiKey = async (apiKey: string) => {
    setApiStatus("loading");
    setShowApiMessage(true);
    try {
      if (!llmDescriptor) {
        setApiStatus("error");
        return;
      }
      const response = await fetch("/api/admin/llm/test", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          api_key: apiKey,
          provider: llmDescriptor.name,
          api_key_changed: true,
          default_model_name: initialValues.default_model_name,
          model_configurations: [
            {
              name: initialValues.default_model_name,
              is_visible: true,
            },
          ],
        }),
      });
      if (!response.ok) {
        const errorMsg = (await response.json()).detail;
        setErrorMessage(errorMsg);
        setApiStatus("error");
        return;
      }
      setApiStatus("success");
    } catch (error) {
      setApiStatus("error");
      setErrorMessage("An error occurred while testing the API key.");
    }
  };

  if (!data) return null;

  return (
    <Modal
      id={ModalIds.LLMConnectionModal}
      title={title}
      description={modalContent.description}
      startAdornment={icon}
      xs
    >
      <Formik
        initialValues={initialValues}
        onSubmit={async (values, { setSubmitting }) => {
          const api_key = values.api_key;
          const payload = {
            ...initialValues,
            ...values,
          };
          console.log("payload", payload);
          const response = await fetch(
            `${LLM_PROVIDERS_ADMIN_URL}${"?is_creation=true"}`,
            {
              method: "PUT",
              headers: {
                "Content-Type": "application/json",
              },
              body: JSON.stringify({
                ...payload,
              }),
            }
          );
          if (!response.ok) {
            const errorMsg = (await response.json()).detail;
            console.log("errorMsg", errorMsg);
            return;
          }
        }}
      >
        <Form className="flex flex-col gap-0">
          <div className="flex flex-col p-4 gap-4 bg-background-tint-01 w-full">
            {llmDescriptor?.api_key_required && (
              <FormikField<string>
                name="api_key"
                render={(field, helper, meta, state) => (
                  <FormField name="api_key" state={state} className="w-full">
                    <FormField.Label>API Key</FormField.Label>
                    <FormField.Control>
                      <PasswordInputTypeIn
                        {...field}
                        placeholder=""
                        onBlur={(e) => {
                          field.onBlur(e);
                          if (field.value) {
                            testApiKey(field.value);
                          }
                        }}
                        showClearButton={false}
                      />
                    </FormField.Control>
                    {!showApiMessage && (
                      <FormField.Description>
                        {"Paste your "}
                        {modalContent?.field_metadata?.api_key ? (
                          <a
                            href={modalContent.field_metadata.api_key}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="underline"
                          >
                            API key
                          </a>
                        ) : (
                          "API key"
                        )}
                        {" from OpenAI to access your models."}
                      </FormField.Description>
                    )}
                    {showApiMessage && (
                      <FormField.APIMessage
                        state={apiStatus}
                        messages={{
                          loading: `Checking API key with ${modalContent?.display_name}...`,
                          success:
                            "API key valid. Your available models updated.",
                          error: errorMessage || "Invalid API key",
                        }}
                      />
                    )}
                  </FormField>
                )}
              />
            )}
            <Separator className="my-0" />
            <FormikField<string>
              name="default_model_name"
              render={(field, helper, meta, state) => (
                <FormField
                  name="default_model_name"
                  state={state}
                  className="w-full"
                >
                  <FormField.Label>Default Model</FormField.Label>
                  <FormField.Control>
                    <InputSelect
                      value={field.value}
                      onValueChange={(value) => helper.setValue(value)}
                      options={modelOptions}
                    />
                  </FormField.Control>
                  <FormField.Description>
                    {modalContent?.field_metadata?.default_model_name}
                  </FormField.Description>
                </FormField>
              )}
            />
          </div>
          <div className="flex justify-end gap-2 w-full p-4">
            <Button
              type="button"
              secondary
              onClick={() => toggleModal(ModalIds.LLMConnectionModal, false)}
            >
              Cancel
            </Button>
            <Button type="submit">Connect</Button>
          </div>
        </Form>
      </Formik>
    </Modal>
  );
};

export default LLMConnectionModal;
