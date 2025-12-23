import { Label, MultiSelectField, SubLabel } from "@/components/Field";
import { ModelConfiguration } from "../../interfaces";
import { FormikProps } from "formik";
import { BaseLLMFormValues } from "../formUtils";

import Text from "@/refresh-components/texts/Text";
import SvgX from "@opal/icons/x";
import InputComboBox from "@/refresh-components/inputs/InputComboBox";

const DISPLAY_MODELS_LABEL = "Display Models";
const DISPLAY_MODELS_SUBTEXT =
  "Select the models to make available to users. Unselected models will not be available.";

function DisplayModelHeader() {
  return (
    <div className="mb-2">
      <label className="block font-medium text-base">Available Models</label>
      <span className="block text-sm text-text-03">
        Select which models to make available for this provider.
      </span>
    </div>
  );
}

export function DisplayModels<T extends BaseLLMFormValues>({
  formikProps,
  modelConfigurations,
  noModelConfigurationsMessage,
  isLoading,
}: {
  formikProps: FormikProps<T>;
  modelConfigurations: ModelConfiguration[];
  noModelConfigurationsMessage: string;
  isLoading: boolean;
}) {
  if (isLoading) {
    return (
      <div>
        <DisplayModelHeader />
        <div className="mt-2 flex items-center p-3 border border-border-01 rounded-lg bg-background-neutral-00">
          <div className="h-5 w-5 animate-spin rounded-full border-2 border-border-03 border-t-action-link-05" />
        </div>
      </div>
    );
  }

  return (
    <div key="manual-mode" className="animate-fadeIn">
      <DisplayModelHeader />
      <div className="flex flex-col gap-2 w-full">
        <InputComboBox
          placeholder="Select your models"
          value=""
          options={modelConfigurations
            .filter(
              (m) => !formikProps.values.selected_model_names?.includes(m.name)
            )
            .map((modelConfiguration) => ({
              label: modelConfiguration.name,
              value: modelConfiguration.name,
            }))}
          onValueChange={(value) => {
            const currentSelected =
              formikProps.values.selected_model_names ?? [];
            const modelName = String(value);
            if (!currentSelected.includes(modelName)) {
              // Add to selected models
              formikProps.setFieldValue("selected_model_names", [
                ...currentSelected,
                modelName,
              ]);
              // If this is the first model, set it as default
              if (currentSelected.length === 0) {
                formikProps.setFieldValue("default_model_name", modelName);
              }
            }
          }}
        />
        {(formikProps.values.selected_model_names?.length ?? 0) > 0 && (
          <div className="flex flex-wrap gap-2 mt-1">
            {[...(formikProps.values.selected_model_names ?? [])].map(
              (modelName) => {
                const isDefault =
                  formikProps.values.default_model_name === modelName;
                return (
                  <div
                    key={modelName}
                    title={isDefault ? undefined : "Click to set as default"}
                    className={`group flex items-center gap-1 rounded-lg border px-2 py-1 text-sm transition-colors ${
                      isDefault
                        ? "border-action-link-05 bg-action-link-05/10"
                        : "border-border-01 bg-background-neutral-00 hover:border-action-link-05/50 cursor-pointer"
                    }`}
                    onClick={() => {
                      if (!isDefault) {
                        formikProps.setFieldValue(
                          "default_model_name",
                          modelName
                        );
                      }
                    }}
                  >
                    <span
                      className={
                        isDefault ? "text-action-link-05 font-medium" : ""
                      }
                    >
                      {modelName}
                    </span>
                    {isDefault && (
                      <span className="text-xs text-action-link-05 ml-1">
                        (default)
                      </span>
                    )}
                    <button
                      type="button"
                      className="p-0.5 rounded hover:bg-background-neutral-03 transition-colors"
                      onClick={(e) => {
                        e.stopPropagation();
                        const currentSelected =
                          formikProps.values.selected_model_names ?? [];
                        const newSelected = currentSelected.filter(
                          (name) => name !== modelName
                        );
                        formikProps.setFieldValue(
                          "selected_model_names",
                          newSelected
                        );
                        // If removing the default, set the first remaining model as default
                        if (isDefault && newSelected.length > 0) {
                          formikProps.setFieldValue(
                            "default_model_name",
                            newSelected[0]
                          );
                        }
                      }}
                    >
                      <SvgX className="h-3.5 w-3.5" />
                    </button>
                  </div>
                );
              }
            )}
          </div>
        )}
      </div>
    </div>
  );

  return (
    <div className="w-full">
      {modelConfigurations.length > 0 ? (
        <MultiSelectField
          selectedInitially={formikProps.values.selected_model_names ?? []}
          name="selected_model_names"
          label={DISPLAY_MODELS_LABEL}
          subtext={DISPLAY_MODELS_SUBTEXT}
          options={modelConfigurations.map((modelConfiguration) => ({
            value: modelConfiguration.name,
            // don't clean up names here to give admins descriptive names / handle duplicates
            // like us.anthropic.claude-3-7-sonnet-20250219-v1:0 and anthropic.claude-3-7-sonnet-20250219-v1:0
            label: modelConfiguration.name,
          }))}
          onChange={(selected) =>
            formikProps.setFieldValue("selected_model_names", selected)
          }
        />
      ) : (
        <div className="mb-6">
          <Label>{DISPLAY_MODELS_LABEL}</Label>
          <Text text03>{noModelConfigurationsMessage}</Text>
        </div>
      )}
    </div>
  );
}
