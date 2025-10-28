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

type LLMConnectionModalData = {
  icon: React.ReactNode;
  title: string;
  llmDescriptor: WellKnownLLMProviderDescriptor;
};

const LLMConnectionModal = () => {
  const { getModalData, toggleModal } = useChatModal();
  const data = getModalData<LLMConnectionModalData>();
  if (!data) return null;

  const { icon, title, llmDescriptor } = data;
  const modalContent = MODAL_CONTENT_MAP[llmDescriptor.name];
  const modelOptions = useMemo(
    () =>
      llmDescriptor.model_configurations.map((model) => ({
        label: model.name,
        value: model.name,
      })),
    [llmDescriptor.model_configurations]
  );

  const initialValues = useMemo(
    () => ({
      default_model_name: llmDescriptor.default_model,
      api_key: "",
    }),
    [llmDescriptor]
  );

  const [apiStatus, setApiStatus] = useState<APIFormFieldState>("loading");
  const [showApiMessage, setShowApiMessage] = useState(false);
  const isApiError = apiStatus === "error";

  const testApiKey = async (apiKey: string) => {
    setApiStatus("loading");
    setShowApiMessage(true);
    try {
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
        setApiStatus("error");
        return;
      }
      setApiStatus("success");
    } catch (error) {
      setApiStatus("error");
    }
  };

  return (
    <Modal
      id={ModalIds.LLMConnectionModal}
      title={title}
      description={modalContent.description}
      startAdornment={icon}
      xs
    >
      <Formik initialValues={initialValues} onSubmit={() => {}}>
        <Form className="flex flex-col gap-0">
          <div className="flex flex-col p-spacing-paragraph gap-spacing-paragraph bg-background-tint-01 w-full">
            {llmDescriptor.api_key_required && (
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
                          error: "Invalid API key",
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
          <div className="flex justify-end gap-spacing-interline w-full p-spacing-paragraph">
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
