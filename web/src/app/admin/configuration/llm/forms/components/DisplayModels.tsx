import { Label, SubLabel } from "@/components/Field";
import { ModelConfiguration } from "../../interfaces";
import { FormikProps } from "formik";
import { BaseLLMFormValues } from "../formUtils";

import Checkbox from "@/refresh-components/inputs/Checkbox";

function DisplayModelHeader({ alternativeText }: { alternativeText?: string }) {
  return (
    <div className="mb-2">
      <label className="block font-medium text-base">Available Models</label>
      <span className="block text-sm text-text-03">
        {alternativeText ??
          "Select which models to make available for this provider."}
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
  noModelConfigurationsMessage?: string;
  isLoading?: boolean;
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

  const handleCheckboxChange = (modelName: string, checked: boolean) => {
    // Read current values inside the handler to avoid stale closure issues
    const currentSelected = formikProps.values.selected_model_names ?? [];
    const currentDefault = formikProps.values.default_model_name;

    if (checked) {
      const newSelected = [...currentSelected, modelName];
      formikProps.setFieldValue("selected_model_names", newSelected);
      // If this is the first model, set it as default
      if (currentSelected.length === 0) {
        formikProps.setFieldValue("default_model_name", modelName);
      }
    } else {
      const newSelected = currentSelected.filter((name) => name !== modelName);
      formikProps.setFieldValue("selected_model_names", newSelected);
      // If removing the default, set the first remaining model as default
      if (currentDefault === modelName && newSelected.length > 0) {
        formikProps.setFieldValue("default_model_name", newSelected[0]);
      } else if (newSelected.length === 0) {
        formikProps.setFieldValue("default_model_name", null);
      }
    }
  };

  const handleSetDefault = (modelName: string) => {
    formikProps.setFieldValue("default_model_name", modelName);
  };

  const selectedModels = formikProps.values.selected_model_names ?? [];
  const defaultModel = formikProps.values.default_model_name;

  // Sort models: default first, then selected, then unselected
  const sortedModelConfigurations = [...modelConfigurations].sort((a, b) => {
    const aIsDefault = a.name === defaultModel;
    const bIsDefault = b.name === defaultModel;
    const aIsSelected = selectedModels.includes(a.name);
    const bIsSelected = selectedModels.includes(b.name);

    if (aIsDefault && !bIsDefault) return -1;
    if (!aIsDefault && bIsDefault) return 1;
    if (aIsSelected && !bIsSelected) return -1;
    if (!aIsSelected && bIsSelected) return 1;
    return 0;
  });

  if (modelConfigurations.length === 0) {
    return (
      <div>
        <DisplayModelHeader
          alternativeText={noModelConfigurationsMessage ?? "No models found"}
        />
      </div>
    );
  }

  return (
    <div>
      <DisplayModelHeader />
      <div className="flex flex-col gap-1 max-h-80 overflow-y-auto border border-border-01 rounded-lg p-3">
        {sortedModelConfigurations.map((modelConfiguration) => {
          const isSelected = selectedModels.includes(modelConfiguration.name);
          const isDefault = defaultModel === modelConfiguration.name;

          return (
            <div
              key={modelConfiguration.name}
              className="flex items-center justify-between py-1.5 px-2 rounded hover:bg-background-neutral-subtle"
            >
              <div
                className="flex items-center gap-2 cursor-pointer"
                onClick={() =>
                  handleCheckboxChange(modelConfiguration.name, !isSelected)
                }
              >
                <div
                  className="flex items-center"
                  onClick={(e) => e.stopPropagation()}
                >
                  <Checkbox
                    checked={isSelected}
                    onCheckedChange={(checked) =>
                      handleCheckboxChange(modelConfiguration.name, checked)
                    }
                  />
                </div>
                <span className="text-sm select-none leading-none">
                  {modelConfiguration.name}
                </span>
              </div>
              <button
                type="button"
                onClick={() => handleSetDefault(modelConfiguration.name)}
                className={`text-xs px-2 py-0.5 rounded transition-all duration-200 ease-in-out ${
                  isSelected
                    ? "opacity-100 translate-x-0"
                    : "opacity-0 translate-x-2 pointer-events-none"
                } ${
                  isDefault
                    ? "bg-action-link-05 text-text-inverse font-medium scale-100"
                    : "bg-background-neutral-02 text-text-03 hover:bg-background-neutral-03 scale-95 hover:scale-100"
                }`}
              >
                {isDefault ? "Default" : "Set as default"}
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
