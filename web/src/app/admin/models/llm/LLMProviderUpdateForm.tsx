import { LoadingAnimation } from "@/components/Loading";
import { AdvancedOptionsToggle } from "@/components/AdvancedOptionsToggle";
import { Button, Divider, Text } from "@tremor/react";
import { Form, Formik } from "formik";
import { FiTrash } from "react-icons/fi";
import { LLM_PROVIDERS_ADMIN_URL } from "./constants";
import {
  SelectorFormField,
  TextFormField,
  BooleanFormField,
  MultiSelectField,
} from "@/components/admin/connectors/Field";
import { useState } from "react";
import { Bubble } from "@/components/Bubble";
import { GroupsIcon } from "@/components/icons/icons";
import { useSWRConfig } from "swr";
import {
  defaultModelsByProvider,
  getDisplayNameForModel,
  useUserGroups,
} from "@/lib/hooks";
import { FullLLMProvider, WellKnownLLMProviderDescriptor } from "./interfaces";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";
import * as Yup from "yup";
import isEqual from "lodash/isEqual";

export function LLMProviderUpdateForm({
  llmProviderDescriptor,
  onClose,
  existingLlmProvider,
  shouldMarkAsDefault,
  setPopup,
}: {
  llmProviderDescriptor: WellKnownLLMProviderDescriptor;
  onClose: () => void;
  existingLlmProvider?: FullLLMProvider;
  shouldMarkAsDefault?: boolean;
  setPopup?: (popup: PopupSpec) => void;
}) {
  const { mutate } = useSWRConfig();

  const isPaidEnterpriseFeaturesEnabled = usePaidEnterpriseFeaturesEnabled();

  // EE only
  const { data: userGroups, isLoading: userGroupsIsLoading } = useUserGroups();

  const [isTesting, setIsTesting] = useState(false);
  const [testError, setTestError] = useState<string>("");

  const [showAdvancedOptions, setShowAdvancedOptions] = useState(false);

  // Define the initial values based on the provider's requirements
  const initialValues = {
    name: existingLlmProvider?.name ?? "",
    api_key: existingLlmProvider?.api_key ?? "",
    api_base: existingLlmProvider?.api_base ?? "",
    api_version: existingLlmProvider?.api_version ?? "",
    default_model_name:
      existingLlmProvider?.default_model_name ??
      (llmProviderDescriptor.default_model ||
        llmProviderDescriptor.llm_names[0]),
    fast_default_model_name:
      existingLlmProvider?.fast_default_model_name ??
      (llmProviderDescriptor.default_fast_model || null),
    custom_config:
      existingLlmProvider?.custom_config ??
      llmProviderDescriptor.custom_config_keys?.reduce(
        (acc, customConfigKey) => {
          acc[customConfigKey.name] = "";
          return acc;
        },
        {} as { [key: string]: string }
      ),
    is_public: existingLlmProvider?.is_public ?? true,
    groups: existingLlmProvider?.groups ?? [],
    display_model_names:
      existingLlmProvider?.display_model_names ||
      defaultModelsByProvider[llmProviderDescriptor.name] ||
      [],
  };

  // Setup validation schema if required
  const validationSchema = Yup.object({
    name: Yup.string().required("Display Name is required"),
    api_key: llmProviderDescriptor.api_key_required
      ? Yup.string().required("API Key is required")
      : Yup.string(),
    api_base: llmProviderDescriptor.api_base_required
      ? Yup.string().required("API Base is required")
      : Yup.string(),
    api_version: llmProviderDescriptor.api_version_required
      ? Yup.string().required("API Version is required")
      : Yup.string(),
    ...(llmProviderDescriptor.custom_config_keys
      ? {
          custom_config: Yup.object(
            llmProviderDescriptor.custom_config_keys.reduce(
              (acc, customConfigKey) => {
                if (customConfigKey.is_required) {
                  acc[customConfigKey.name] = Yup.string().required(
                    `${customConfigKey.name} is required`
                  );
                }
                return acc;
              },
              {} as { [key: string]: Yup.StringSchema }
            )
          ),
        }
      : {}),
    default_model_name: Yup.string().required("Model name is required"),
    fast_default_model_name: Yup.string().nullable(),
    // EE Only
    is_public: Yup.boolean().required(),
    groups: Yup.array().of(Yup.number()),
    display_model_names: Yup.array().of(Yup.string()),
  });

  return (
    <Formik
      initialValues={initialValues}
      validationSchema={validationSchema}
      onSubmit={async (values, { setSubmitting }) => {
        setSubmitting(true);

        // test the configuration
        if (!isEqual(values, initialValues)) {
          setIsTesting(true);

          const response = await fetch("/api/admin/llm/test", {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
            },
            body: JSON.stringify({
              provider: llmProviderDescriptor.name,
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
            provider: llmProviderDescriptor.name,
            ...values,
            fast_default_model_name:
              values.fast_default_model_name || values.default_model_name,
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
      {({ values, setFieldValue }) => (
        <Form>
          <TextFormField
            name="name"
            label="Display Name"
            subtext="A name which you can use to identify this provider when selecting it in the UI."
            placeholder="Display Name"
            disabled={existingLlmProvider ? true : false}
          />

          <Divider />

          {llmProviderDescriptor.api_key_required && (
            <TextFormField
              name="api_key"
              label="API Key"
              placeholder="API Key"
              type="password"
            />
          )}

          {llmProviderDescriptor.api_base_required && (
            <TextFormField
              name="api_base"
              label="API Base"
              placeholder="API Base"
            />
          )}

          {llmProviderDescriptor.api_version_required && (
            <TextFormField
              name="api_version"
              label="API Version"
              placeholder="API Version"
            />
          )}

          {llmProviderDescriptor.custom_config_keys?.map((customConfigKey) => (
            <div key={customConfigKey.name}>
              <TextFormField
                name={`custom_config.${customConfigKey.name}`}
                label={
                  customConfigKey.is_required
                    ? customConfigKey.name
                    : `[Optional] ${customConfigKey.name}`
                }
                subtext={customConfigKey.description || undefined}
              />
            </div>
          ))}

          <Divider />

          {llmProviderDescriptor.llm_names.length > 0 ? (
            <SelectorFormField
              name="default_model_name"
              subtext="The model to use by default for this provider unless otherwise specified."
              label="Default Model"
              options={llmProviderDescriptor.llm_names.map((name) => ({
                name: getDisplayNameForModel(name),
                value: name,
              }))}
              maxHeight="max-h-56"
            />
          ) : (
            <TextFormField
              name="default_model_name"
              subtext="The model to use by default for this provider unless otherwise specified."
              label="Default Model"
              placeholder="E.g. gpt-4"
            />
          )}

          {llmProviderDescriptor.llm_names.length > 0 ? (
            <SelectorFormField
              name="fast_default_model_name"
              subtext={`The model to use for lighter flows like \`LLM Chunk Filter\` 
                for this provider. If \`Default\` is specified, will use 
                the Default Model configured above.`}
              label="[Optional] Fast Model"
              options={llmProviderDescriptor.llm_names.map((name) => ({
                name: getDisplayNameForModel(name),
                value: name,
              }))}
              includeDefault
              maxHeight="max-h-56"
            />
          ) : (
            <TextFormField
              name="fast_default_model_name"
              subtext={`The model to use for lighter flows like \`LLM Chunk Filter\` 
                for this provider. If \`Default\` is specified, will use 
                the Default Model configured above.`}
              label="[Optional] Fast Model"
              placeholder="E.g. gpt-4"
            />
          )}

          <Divider />

          {llmProviderDescriptor.name != "azure" && (
            <AdvancedOptionsToggle
              showAdvancedOptions={showAdvancedOptions}
              setShowAdvancedOptions={setShowAdvancedOptions}
            />
          )}

          {showAdvancedOptions && (
            <>
              {llmProviderDescriptor.llm_names.length > 0 && (
                <div className="w-full">
                  <MultiSelectField
                    selectedInitially={values.display_model_names}
                    name="display_model_names"
                    label="Display Models"
                    subtext="Select the models to make available to users. Unselected models will not be available."
                    options={llmProviderDescriptor.llm_names.map((name) => ({
                      value: name,
                      label: getDisplayNameForModel(name),
                    }))}
                    onChange={(selected) =>
                      setFieldValue("display_model_names", selected)
                    }
                  />
                </div>
              )}

              {isPaidEnterpriseFeaturesEnabled && userGroups && (
                <>
                  <BooleanFormField
                    small
                    noPadding
                    alignTop
                    name="is_public"
                    label="Is Public?"
                    subtext="If set, this LLM Provider will be available to all users. If not, only the specified User Groups will be able to use it."
                  />

                  {userGroups && userGroups.length > 0 && !values.is_public && (
                    <div>
                      <Text>
                        Select which User Groups should have access to this LLM
                        Provider.
                      </Text>
                      <div className="flex flex-wrap gap-2 mt-2">
                        {userGroups.map((userGroup) => {
                          const isSelected = values.groups.includes(
                            userGroup.id
                          );
                          return (
                            <Bubble
                              key={userGroup.id}
                              isSelected={isSelected}
                              onClick={() => {
                                if (isSelected) {
                                  setFieldValue(
                                    "groups",
                                    values.groups.filter(
                                      (id) => id !== userGroup.id
                                    )
                                  );
                                } else {
                                  setFieldValue("groups", [
                                    ...values.groups,
                                    userGroup.id,
                                  ]);
                                }
                              }}
                            >
                              <div className="flex">
                                <GroupsIcon />
                                <div className="ml-1">{userGroup.name}</div>
                              </div>
                            </Bubble>
                          );
                        })}
                      </div>
                    </div>
                  )}
                </>
              )}
            </>
          )}
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
