import type { ReactNode } from "react";
import { FormikProps } from "formik";
import { useTranslations } from "next-intl";
import { InputSingleSelect, Tag } from "@opal/components";
import Text from "@/refresh-components/texts/Text";
import { useUserGroups } from "@/lib/hooks";
import { useTierAtLeast } from "@/hooks/useTierAtLeast";
import { Tier } from "@/lib/settings/types";

export type CredentialGroupsFormType = {
  groups: number[];
};

interface CredentialGroupsFieldProps<T extends CredentialGroupsFormType> {
  formikProps: FormikProps<T>;
  // Scoped managers see the "groups you manage" wording.
  isGlobalHolder: boolean;
}

// Group picker for the credential form. Business tier only; renders nothing otherwise.
export function CredentialGroupsField<T extends CredentialGroupsFormType>({
  formikProps,
  isGlobalHolder,
}: CredentialGroupsFieldProps<T>) {
  const t = useTranslations("common.isPublicSelector");
  const tSelect = useTranslations("common.genericMultiSelect");
  const tGroups = useTranslations("common.groupsMultiSelect");
  const businessTier = useTierAtLeast(Tier.BUSINESS);
  const { data: userGroups, isLoading, error } = useUserGroups();

  const objectName = "credential";
  const label = t("assignGroups.label", { objectName });

  if (businessTier === undefined || isLoading) {
    return (
      <div className="flex flex-col gap-2 w-full">
        <Text as="p" mainUiAction>
          {label}
        </Text>
        <div className="animate-pulse bg-background-neutral-02 h-10 w-full rounded-08" />
      </div>
    );
  }
  if (!businessTier) {
    return null;
  }

  const groups = userGroups ?? [];
  const selectedIds = formikProps.values.groups;
  const selectedGroups = groups.filter((group) =>
    selectedIds.includes(group.id)
  );

  const handleSelect = (value: string) => {
    const id = Number(value);
    if (Number.isNaN(id) || selectedIds.includes(id)) return;
    formikProps.setFieldValue("groups", [...selectedIds, id]);
  };

  const handleRemove = (id: number) => {
    formikProps.setFieldValue(
      "groups",
      selectedIds.filter((selectedId) => selectedId !== id)
    );
  };

  let body: ReactNode;
  if (error) {
    body = (
      <Text as="p" text03 className="text-action-danger-05">
        {tSelect("loadFailed.text", { label: label.toLowerCase() })}
      </Text>
    );
  } else if (groups.length === 0) {
    body = (
      <Text as="p" text03>
        {tGroups("noGroups.emptyMessage")}
      </Text>
    );
  } else {
    body = (
      <>
        <InputSingleSelect
          placeholder={tSelect("search.placeholder")}
          value=""
          onChange={() => {}}
          onValueChange={handleSelect}
          options={groups
            .filter((group) => !selectedIds.includes(group.id))
            .map((group) => ({ label: group.name, value: String(group.id) }))}
          searchIcon
          data-testid="groups-search-input"
        />
        {selectedGroups.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {selectedGroups.map((group) => (
              <Tag
                key={group.id}
                size="md"
                title={group.name}
                onRemove={() => handleRemove(group.id)}
              />
            ))}
          </div>
        )}
      </>
    );
  }

  return (
    <div className="flex flex-col gap-2 w-full">
      <Text as="p" mainUiAction>
        {label}
      </Text>
      <Text as="p" text03>
        {isGlobalHolder
          ? t("assignGroups.visibleSubtext", { objectName })
          : t("assignGroups.scopedSubtext", { objectName })}
      </Text>
      {body}
    </div>
  );
}
