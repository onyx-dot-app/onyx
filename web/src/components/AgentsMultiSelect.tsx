import { FormikProps } from "formik";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
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
  label?: string;
  subtext?: string;
}

export function AgentsMultiSelect<T extends AgentsMultiSelectFormType>({
  formikProps,
  label = "Agents",
  subtext = "Select which agents can use this LLM provider. If none selected, all agents can use it.",
}: AgentsMultiSelectProps<T>) {
  const {
    data: agents,
    isLoading,
    error,
  } = useSWR<Agent[]>("/api/persona", errorHandlingFetcher);

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
    />
  );
}
