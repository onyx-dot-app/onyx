import { FormikProps } from "formik";
import { AdvancedOptionsToggle } from "@/components/AdvancedOptionsToggle";
import { IsPublicGroupSelector } from "@/components/IsPublicGroupSelector";
import { AgentsMultiSelect } from "@/components/AgentsMultiSelect";
import Text from "@/refresh-components/texts/Text";
import { useState } from "react";
import { useAgents } from "@/hooks/useAgents";

export function AdvancedOptions({
  formikProps,
}: {
  formikProps: FormikProps<any>;
}) {
  const { agents, isLoading: agentsLoading, error: agentsError } = useAgents();
  const [showAdvancedOptions, setShowAdvancedOptions] = useState(false);

  return (
    <>
      <AdvancedOptionsToggle
        showAdvancedOptions={showAdvancedOptions}
        setShowAdvancedOptions={setShowAdvancedOptions}
      />

      {showAdvancedOptions && (
        <>
          <div className="flex flex-col gap-3">
            <Text as="p" headingH3>
              Access Controls
            </Text>
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
