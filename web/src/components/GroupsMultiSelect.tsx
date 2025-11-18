import { FormikProps } from "formik";
import { Label } from "@/components/Field";
import { useUserGroups } from "@/lib/hooks";
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";
import { GenericMultiSelect } from "@/components/GenericMultiSelect";

export type GroupsMultiSelectFormType = {
  groups: number[];
};

interface GroupsMultiSelectProps<T extends GroupsMultiSelectFormType> {
  formikProps: FormikProps<T>;
  label?: string;
  subtext?: string;
  disabled?: boolean;
  disabledMessage?: string;
}

export function GroupsMultiSelect<T extends GroupsMultiSelectFormType>({
  formikProps,
  label = "User Groups",
  subtext = "Select which user groups can access this resource",
  disabled = false,
  disabledMessage,
}: GroupsMultiSelectProps<T>) {
  const {
    data: userGroups,
    isLoading: userGroupsIsLoading,
    error,
  } = useUserGroups();
  const isPaidEnterpriseFeaturesEnabled = usePaidEnterpriseFeaturesEnabled();

  // Show loading state while checking enterprise features or loading groups
  if (userGroupsIsLoading || isPaidEnterpriseFeaturesEnabled === undefined) {
    return (
      <div className="mb-4">
        <Label>{label}</Label>
        <div className="animate-pulse bg-background-200 h-10 w-full rounded-lg mt-2"></div>
      </div>
    );
  }

  if (!isPaidEnterpriseFeaturesEnabled) {
    return null;
  }

  return (
    <GenericMultiSelect
      formikProps={formikProps}
      fieldName="groups"
      label={label}
      subtext={subtext}
      items={userGroups}
      isLoading={false}
      error={error}
      emptyMessage="No user groups available. Please create a user group first."
      disabled={disabled}
      disabledMessage={disabledMessage}
    />
  );
}
