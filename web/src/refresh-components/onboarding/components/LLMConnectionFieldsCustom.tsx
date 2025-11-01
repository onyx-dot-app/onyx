import React, { useState } from "react";
import { FormikField } from "@/refresh-components/form/FormikField";
import { FormField } from "@/refresh-components/form/FormField";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import PasswordInputTypeIn from "@/refresh-components/inputs/PasswordInputTypeIn";
import { Separator } from "@/components/ui/separator";
import KeyValueInput, {
  KeyValue,
} from "@/refresh-components/inputs/InputKeyValue";
import Text from "@/refresh-components/texts/Text";
import { useFormikContext } from "formik";

type ModelConfig = {
  name: string;
  max_input_tokens: string;
};

type Props = {
  showApiMessage: boolean;
  apiStatus: "idle" | "loading" | "success" | "error";
  errorMessage: string;
};

export const LLMConnectionFieldsCustom: React.FC<Props> = ({
  showApiMessage,
  apiStatus,
  errorMessage,
}) => {
  const formikContext = useFormikContext<any>();
  const [modelConfigError, setModelConfigError] = useState<string | null>(null);

  const handleModelConfigsChange = (items: KeyValue[]) => {
    // Don't filter out empty items here - let the user edit them
    const configs = items.map((item) => ({
      name: item.key,
      is_visible: true,
      max_input_tokens:
        item.value.trim() === "" ? null : parseInt(item.value, 10),
      supports_image_input: false,
    }));

    formikContext.setFieldValue("model_configurations", configs);
  };

  const handleCustomConfigsChange = (items: KeyValue[]) => {
    // Convert KeyValue[] to Record<string, string>
    // Don't filter out empty items here - let the user edit them
    const config: Record<string, string> = {};
    items.forEach((item) => {
      config[item.key] = item.value;
    });
    formikContext.setFieldValue("custom_config", config);
  };

  // Convert model_configurations back to KeyValue[] for display
  const modelConfigsAsKeyValue: KeyValue[] =
    formikContext.values.model_configurations?.map((config: any) => ({
      key: config.name || "",
      value: config.max_input_tokens?.toString() || "",
    })) || [];

  // Convert custom_config back to KeyValue[] for display
  const customConfigAsKeyValue: KeyValue[] = Object.entries(
    formikContext.values.custom_config || {}
  ).map(([key, value]) => ({
    key,
    value: value as string,
  }));

  return (
    <>
      <FormikField<string>
        name="provider"
        render={(field, helper, meta, state) => (
          <FormField name="provider" state={state} className="w-full">
            <FormField.Label>Provider Name</FormField.Label>
            <FormField.Control>
              <InputTypeIn
                {...field}
                placeholder="E.g. openai, anthropic, etc."
                showClearButton={false}
              />
            </FormField.Control>
            <FormField.Message
              messages={{
                idle: (
                  <>
                    See full list of supported LLM providers at{" "}
                    <a
                      href="https://docs.litellm.ai/docs/providers"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="underline"
                    >
                      LiteLLM
                    </a>
                    .
                  </>
                ),
                error: meta.error,
              }}
            />
          </FormField>
        )}
      />

      <Separator className="my-0" />

      <Text text03 secondaryBody className="ml-0.5">
        Fill in the following fields as needed. Refer to{" "}
        <a
          href="https://docs.litellm.ai/docs/"
          target="_blank"
          rel="noopener noreferrer"
          className="underline"
        >
          LiteLLM documentation
        </a>{" "}
        for instructions of the model provider you are using.
      </Text>

      <FormikField<string>
        name="api_base"
        render={(field, helper, meta, state) => (
          <FormField name="api_base" state={state} className="w-full">
            <FormField.Label optional>API Base URL</FormField.Label>
            <FormField.Control>
              <InputTypeIn
                {...field}
                placeholder="https://"
                showClearButton={false}
              />
            </FormField.Control>
          </FormField>
        )}
      />

      <FormikField<string>
        name="api_version"
        render={(field, helper, meta, state) => (
          <FormField name="api_version" state={state} className="w-full">
            <FormField.Label optional>API Version</FormField.Label>
            <FormField.Control>
              <InputTypeIn {...field} placeholder="" showClearButton={false} />
            </FormField.Control>
          </FormField>
        )}
      />

      <FormikField<string>
        name="api_key"
        render={(field, helper, meta, state) => (
          <FormField name="api_key" state={state} className="w-full">
            <FormField.Label optional>API Key</FormField.Label>
            <FormField.Control>
              <PasswordInputTypeIn
                {...field}
                placeholder=""
                showClearButton={false}
              />
            </FormField.Control>
          </FormField>
        )}
      />

      <Separator className="my-0" />

      <div className="w-full">
        <FormField
          name="custom_config"
          state={formikContext.errors.custom_config ? "error" : "idle"}
          className="w-full"
        >
          <FormField.Label optional>Additional Configs</FormField.Label>
          <FormField.Description>
            Optional additional properties as needed by the model provider. This
            is passed to LiteLLM{" "}
            <Text text03 secondaryMono nowrap className="inline-block">
              completion()
            </Text>{" "}
            call as arguments in the environment variable.
          </FormField.Description>
          <FormField.Control asChild>
            <KeyValueInput
              keyTitle="Key"
              valueTitle="Value"
              items={customConfigAsKeyValue}
              onChange={handleCustomConfigsChange}
              mode="line"
            />
          </FormField.Control>
        </FormField>
      </div>

      <Separator className="my-0" />

      <div className="w-full">
        <FormField
          name="model_configurations"
          state={
            formikContext.errors.model_configurations || modelConfigError
              ? "error"
              : "idle"
          }
          className="w-full"
        >
          <FormField.Label>Model Configs</FormField.Label>
          <FormField.Description>
            List LLM models you wish to use and their configurations for this
            provider.
          </FormField.Description>
          <FormField.Control asChild>
            <KeyValueInput
              keyTitle="Model Name"
              valueTitle="Max Input Tokens"
              items={modelConfigsAsKeyValue}
              onChange={handleModelConfigsChange}
              onValidationError={setModelConfigError}
              mode="fixed-line"
            />
          </FormField.Control>
        </FormField>
      </div>

      <Separator className="my-0" />

      <FormikField<string>
        name="default_model_name"
        render={(field, helper, meta, state) => (
          <FormField name="default_model_name" state={state} className="w-full">
            <FormField.Label>Default Model</FormField.Label>
            <FormField.Control>
              <InputTypeIn
                {...field}
                placeholder="model-name"
                showClearButton={false}
              />
            </FormField.Control>
            <FormField.Message
              messages={{
                idle: "This model will be used by Onyx by default for this provider. This must be one of the models listed above.",
                error: meta.error,
              }}
            />
          </FormField>
        )}
      />

      <FormikField<string>
        name="fast_default_model_name"
        render={(field, helper, meta, state) => (
          <FormField
            name="fast_default_model_name"
            state={state}
            className="w-full"
          >
            <FormField.Label optional>Fast Model</FormField.Label>
            <FormField.Control>
              <InputTypeIn
                {...field}
                placeholder="Use default model"
                showClearButton={false}
              />
            </FormField.Control>
            <FormField.Message
              messages={{
                idle: (
                  <>
                    A <strong>faster</strong>, more{" "}
                    <strong>cost-effective</strong> model for quick background
                    tasks (e.g. categorizing prompts, naming sessions). Falls
                    back to the default model if not specified.
                  </>
                ),
                error: meta.error,
              }}
            />
          </FormField>
        )}
      />
    </>
  );
};
