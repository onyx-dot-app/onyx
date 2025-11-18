import { FormikProps } from "formik";
import { GenericMultiSelect } from "@/components/GenericMultiSelect";

export type AgentsMultiSelectFormType = {
  personas: number[];
};

interface Agent {
  id: number;
  name: string;
  description: string;
}

interface AgentsMultiSelectProps<T extends AgentsMultiSelectFormType> {
  formikProps: FormikProps<T>;
  agents: Agent[] | undefined;
  isLoading?: boolean;
  error?: any;
  label?: string;
  subtext?: string;
  disabled?: boolean;
  disabledMessage?: string;
}

export function AgentsMultiSelect<T extends AgentsMultiSelectFormType>({
  formikProps,
  agents,
  isLoading = false,
  error,
  label = "Agents",
  subtext = "",
  disabled = false,
  disabledMessage,
}: AgentsMultiSelectProps<T>) {
  return (
    <GenericMultiSelect
      formikProps={formikProps}
      fieldName="personas"
      label={label}
      subtext={subtext}
      items={agents}
      isLoading={isLoading}
      error={error}
      emptyMessage="No agents available. Please create an agent first from the Agents page."
      disabled={disabled}
      disabledMessage={disabledMessage}
    />
  );
}
