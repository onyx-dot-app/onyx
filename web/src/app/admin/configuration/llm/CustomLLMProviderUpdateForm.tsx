import i18n from "@/i18n/init";
import k from "./../../../../i18n/keys";
import { LoadingAnimation } from "@/components/Loading";
import Text from "@/components/ui/text";
import { Separator } from "@/components/ui/separator";
import { Button } from "@/components/ui/button";
import { AdvancedOptionsToggle } from "@/components/AdvancedOptionsToggle";
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
import { LLMProviderView } from "./interfaces";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import * as Yup from "yup";
import isEqual from "lodash/isEqual";
import { IsPublicGroupSelector } from "@/components/IsPublicGroupSelector";
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";

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
  hideSuccess,
}: {
  onClose: () => void;
  existingLlmProvider?: LLMProviderView;
  shouldMarkAsDefault?: boolean;
  setPopup?: (popup: PopupSpec) => void;
  hideSuccess?: boolean;
}) {
  const { mutate } = useSWRConfig();

  const [isTesting, setIsTesting] = useState(false);
  const [testError, setTestError] = useState<string>("");

  const [showAdvancedOptions, setShowAdvancedOptions] = useState(false);

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
    is_public: existingLlmProvider?.is_public ?? true,
    groups: existingLlmProvider?.groups ?? [],
    deployment_name: existingLlmProvider?.deployment_name ?? null,
  };

  // Setup validation schema if required
  const validationSchema = Yup.object({
    name: Yup.string().required(i18n.t(k.DISPLAY_NAME_REQUIRED)),
    provider: Yup.string().required(i18n.t(k.PROVIDER_NAME_REQUIRED)),
    api_key: Yup.string(),
    api_base: Yup.string(),
    api_version: Yup.string(),
    model_names: Yup.array(
      Yup.string().required(i18n.t(k.MODEL_NAME_REQUIRED))
    ),
    default_model_name: Yup.string().required(i18n.t(k.MODEL_NAME_REQUIRED)),
    fast_default_model_name: Yup.string().nullable(),
    custom_config_list: Yup.array(),
    // EE Only
    is_public: Yup.boolean().required(),
    groups: Yup.array().of(Yup.number()),
    deployment_name: Yup.string().nullable(),
  });

  const arePaidEnterpriseFeaturesEnabled = usePaidEnterpriseFeaturesEnabled();

  return (
    <Formik
      initialValues={initialValues}
      validationSchema={validationSchema}
      onSubmit={async (values, { setSubmitting }) => {
        setSubmitting(true);

        if (values.model_names.length === 0) {
          const fullErrorMsg = i18n.t(k.AT_LEAST_ONE_MODEL_NAME_IS_REQ);
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
            // For custom llm providers, all model names are displayed
            display_model_names: values.model_names,
            custom_config: customConfigProcessing(values.custom_config_list),
          }),
        });

        if (!response.ok) {
          const errorMsg = (await response.json()).detail;
          const fullErrorMsg = existingLlmProvider
            ? `${i18n.t(k.FAILED_TO_UPDATE_PROVIDER)} ${errorMsg}`
            : `${i18n.t(k.FAILED_TO_ENABLE_PROVIDER)} ${errorMsg}`;
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
          const newLlmProvider = (await response.json()) as LLMProviderView;
          const setDefaultResponse = await fetch(
            `${LLM_PROVIDERS_ADMIN_URL}/${newLlmProvider.id}/default`,
            {
              method: "POST",
            }
          );
          if (!setDefaultResponse.ok) {
            const errorMsg = (await setDefaultResponse.json()).detail;
            const fullErrorMsg = `${i18n.t(
              k.FAILED_TO_SET_PROVIDER_AS_DEFA
            )} ${errorMsg}`;
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
          ? i18n.t(k.PROVIDER_UPDATED_SUCCESSFULLY)
          : i18n.t(k.PROVIDER_ENABLED_SUCCESSFULLY);

        if (!hideSuccess && setPopup) {
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
      {(formikProps) => {
        return (
          <Form className="gap-y-6 mt-8">
            <TextFormField
              name="name"
              label={i18n.t(k.DISPLAY_NAME_LABEL)}
              subtext={i18n.t(k.DISPLAY_NAME_SUBTEXT)}
              placeholder={i18n.t(k.DISPLAY_NAME_PLACEHOLDER)}
              disabled={existingLlmProvider ? true : false}
            />

            <TextFormField
              name="provider"
              label={i18n.t(k.PROVIDER_LABEL)}
              subtext={
                <>
                  {i18n.t(k.SHOULD_BE_ONE_OF_THE_PROVIDERS)}{" "}
                  <a
                    target="_blank"
                    href="https://docs.litellm.ai/docs/providers"
                    className="text-link"
                    rel="noreferrer"
                  >
                    {i18n.t(k.HTTPS_DOCS_LITELLM_AI_DOCS_P)}
                  </a>
                  {i18n.t(k._8)}
                </>
              }
              placeholder={i18n.t(k.PROVIDER_PLACEHOLDER)}
            />

            <Separator />

            <SubLabel>{i18n.t(k.FILL_IN_THE_FOLLOWING_AS_IS_NE)}</SubLabel>

            <TextFormField
              name="api_key"
              label={i18n.t(k.API_KEY_LABEL)}
              placeholder={i18n.t(k.API_KEY_PLACEHOLDER)}
              type="password"
            />

            {existingLlmProvider?.deployment_name && (
              <TextFormField
                name="deployment_name"
                label={i18n.t(k.DEPLOYMENT_NAME_LABEL)}
                placeholder={i18n.t(k.DEPLOYMENT_NAME_PLACEHOLDER)}
              />
            )}

            <TextFormField
              name="api_base"
              label={i18n.t(k.API_BASE_LABEL)}
              placeholder={i18n.t(k.API_BASE_PLACEHOLDER)}
            />

            <TextFormField
              name="api_version"
              label={i18n.t(k.API_VERSION_LABEL)}
              placeholder={i18n.t(k.API_VERSION_PLACEHOLDER)}
            />

            <Label>{i18n.t(k.OPTIONAL_CUSTOM_CONFIGS)}</Label>
            <SubLabel>
              <>
                <div>{i18n.t(k.ADDITIONAL_CONFIGURATIONS_NEED)}</div>

                <div className="mt-2">
                  {i18n.t(k.FOR_EXAMPLE_WHEN_CONFIGURING)}
                </div>
              </>
            </SubLabel>

            <FieldArray
              name="custom_config_list"
              render={(arrayHelpers: ArrayHelpers<any[]>) => (
                <div className="w-full">
                  {formikProps.values.custom_config_list.map((_, index) => {
                    return (
                      <div
                        key={index}
                        className={(index === 0 ? "mt-2" : "mt-6") + " w-full"}
                      >
                        <div className="flex w-full">
                          <div className="w-full mr-6 border border-border p-3 rounded">
                            <div>
                              <Label>{i18n.t(k.KEY2)}</Label>
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
                              <Label>{i18n.t(k.VALUE1)}</Label>
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
                              className="my-auto w-10 h-10 cursor-pointer hover:bg-accent-background-hovered rounded p-2"
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
                    variant="next"
                    type="button"
                    icon={FiPlus}
                  >
                    {i18n.t(k.ADD_NEW)}
                  </Button>
                </div>
              )}
            />

            <Separator />

            {!existingLlmProvider?.deployment_name && (
              <TextArrayField
                name="model_names"
                label={i18n.t(k.MODEL_NAMES_LABEL)}
                values={formikProps.values}
                subtext={
                  <>
                    {i18n.t(k.LIST_THE_INDIVIDUAL_MODELS_THA)}{" "}
                    <a
                      target="_blank"
                      href="https://models.litellm.ai/"
                      className="text-link"
                      rel="noreferrer"
                    >
                      {i18n.t(k.HERE)}
                    </a>
                    {i18n.t(k._8)}
                  </>
                }
              />
            )}

            <Separator />

            <TextFormField
              name="default_model_name"
              subtext={`
              ${i18n.t(k.THE_MODEL_TO_USE_BY_DEFAULT_FO)}`}
              label={i18n.t(k.DEFAULT_MODEL_LABEL)}
              placeholder={i18n.t(k.DEFAULT_MODEL_PLACEHOLDER)}
            />

            {!existingLlmProvider?.deployment_name && (
              <TextFormField
                name="fast_default_model_name"
                subtext={`${i18n.t(k.THE_MODEL_TO_USE_FOR_LIGHTER_F)}`}
                label={i18n.t(k.FAST_MODEL_LABEL)}
                placeholder={i18n.t(k.FAST_MODEL_PLACEHOLDER)}
              />
            )}

            {arePaidEnterpriseFeaturesEnabled && (
              <>
                <Separator />
                <AdvancedOptionsToggle
                  showAdvancedOptions={showAdvancedOptions}
                  setShowAdvancedOptions={setShowAdvancedOptions}
                />

                {showAdvancedOptions && (
                  <IsPublicGroupSelector
                    formikProps={formikProps}
                    objectName="LLM Provider"
                    publicToWhom="all users"
                    enforceGroupSelection={true}
                  />
                )}
              </>
            )}

            <div>
              {/* NOTE: this is above the test button to make sure it's visible */}
              {testError && (
                <Text className="text-error mt-2">{testError}</Text>
              )}

              <div className="flex w-full mt-4">
                <Button type="submit" variant="submit">
                  {isTesting ? (
                    <LoadingAnimation text={i18n.t(k.TESTING_TEXT)} />
                  ) : existingLlmProvider ? (
                    i18n.t(k.UPDATE)
                  ) : (
                    i18n.t(k.ENABLE)
                  )}
                </Button>
                {existingLlmProvider && (
                  <Button
                    type="button"
                    variant="destructive"
                    className="ml-3"
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
                        alert(
                          `${i18n.t(k.FAILED_TO_DELETE_PROVIDER)} ${errorMsg}`
                        );
                        return;
                      }

                      mutate(LLM_PROVIDERS_ADMIN_URL);
                      onClose();
                    }}
                  >
                    {i18n.t(k.DELETE)}
                  </Button>
                )}
              </div>
            </div>
          </Form>
        );
      }}
    </Formik>
  );
}
