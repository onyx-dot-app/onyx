import { FormikProps } from "formik";
import { ModelConfiguration } from "../../interfaces";
import { AdvancedOptionsToggle } from "@/components/AdvancedOptionsToggle";
import { MultiSelectField } from "@/components/Field";
import Separator from "@/refresh-components/Separator";
import { IsPublicGroupSelector } from "@/components/IsPublicGroupSelector";
import { AgentsMultiSelect } from "@/components/AgentsMultiSelect";
import Text from "@/refresh-components/texts/Text";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { useState } from "react";

export function AdvancedOptions({
  currentModelConfigurations,
  formikProps,
}: {
  currentModelConfigurations: ModelConfiguration[];
  formikProps: FormikProps<any>;
}) {
  const {
    data: agents,
    isLoading: agentsLoading,
    error: agentsError,
  } = useSWR<Array<{ id: number; name: string; description: string }>>(
    "/api/persona",
    errorHandlingFetcher
  );
  const [showAdvancedOptions, setShowAdvancedOptions] = useState(false);

  return (
    <>
      <AdvancedOptionsToggle
        showAdvancedOptions={showAdvancedOptions}
        setShowAdvancedOptions={setShowAdvancedOptions}
      />

      {showAdvancedOptions && (
        <>
          {currentModelConfigurations.length > 0 && (
            <div className="w-full">
              <MultiSelectField
                selectedInitially={
                  formikProps.values.selected_model_names ?? []
                }
                name="selected_model_names"
                label="Display Models"
                subtext="Select the models to make available to users. Unselected models will not be available."
                options={currentModelConfigurations.map(
                  (modelConfiguration) => ({
                    value: modelConfiguration.name,
                    label: modelConfiguration.name,
                  })
                )}
                onChange={(selected) =>
                  formikProps.setFieldValue("selected_model_names", selected)
                }
              />
            </div>
          )}

          <Separator />

          <div className="flex flex-col gap-3">
            <Text headingH3>Access Controls</Text>
            <IsPublicGroupSelector
              formikProps={formikProps}
              objectName="LLM Provider"
              publicToWhom="Users"
              enforceGroupSelection={true}
              smallLabels={true}
            />
            <AgentsMultiSelect
              formikProps={formikProps}
              agents={agents}
              isLoading={agentsLoading}
              error={agentsError}
              label="Assistant Whitelist"
              subtext="Restrict this provider to specific assistants."
              disabled={formikProps.values.is_public}
              disabledMessage="This LLM Provider is public and available to all assistants."
            />
          </div>
        </>
      )}
    </>
  );
}
