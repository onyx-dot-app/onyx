import { FormikProps } from "formik";
import { useTranslations } from "next-intl";
import { Label } from "@/components/Field";
import { useUserGroups } from "@/lib/hooks";
import { useTierAtLeast } from "@/hooks/useTierAtLeast";
import { Tier } from "@/lib/settings/types";
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
  label,
  subtext,
  disabled = false,
  disabledMessage,
}: GroupsMultiSelectProps<T>) {
  const t = useTranslations("common.groupsMultiSelect");
  const effectiveLabel = label ?? t("userGroups.label");
  const effectiveSubtext = subtext ?? t("userGroups.subtext");
  const {
    data: userGroups,
    isLoading: userGroupsIsLoading,
    error,
  } = useUserGroups();
  const businessTier = useTierAtLeast(Tier.BUSINESS);

  // Show loading state while checking enterprise features or loading groups
  if (userGroupsIsLoading || businessTier === undefined) {
    return (
      <div className="mb-4">
        <Label>{effectiveLabel}</Label>
        <div className="animate-pulse bg-background-200 h-10 w-full rounded-lg mt-2"></div>
      </div>
    );
  }

  if (!businessTier) {
    return null;
  }

  return (
    <GenericMultiSelect
      formikProps={formikProps}
      fieldName="groups"
      label={effectiveLabel}
      subtext={effectiveSubtext}
      items={userGroups}
      isLoading={false}
      error={error}
      emptyMessage={t("noGroups.emptyMessage")}
      disabled={disabled}
      disabledMessage={disabledMessage}
    />
  );
}
