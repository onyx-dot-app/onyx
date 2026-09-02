import { useTierAtLeast } from "@/hooks/useTierAtLeast";
import { Tier } from "@/lib/settings/types";
import React, { useEffect } from "react";
import { useTranslations } from "next-intl";
import { FormikProps } from "formik";
import { useUserGroups } from "@/lib/hooks";
import { BooleanFormField } from "@/components/Field";
import { useUser } from "@/providers/UserProvider";
import { GroupsMultiSelect } from "./GroupsMultiSelect";

export type IsPublicGroupSelectorFormType = {
  is_public: boolean;
  groups: number[];
};

// This should be included for all forms that require groups / public access
// to be set, and access to this / permissioning should be handled within this component itself.
export const IsPublicGroupSelector = <T extends IsPublicGroupSelectorFormType>({
  formikProps,
  objectName,
  publicToWhom,
  removeIndent = false,
  enforceGroupSelection = true,
  smallLabels = false,
  isGlobalHolder,
}: {
  formikProps: FormikProps<T>;
  objectName: string;
  publicToWhom?: string;
  removeIndent?: boolean;
  enforceGroupSelection?: boolean;
  smallLabels?: boolean;
  // Whether the caller holds this object's manage permission org-wide. The
  // component is shared across connectors, document sets and actions, so each
  // caller supplies its own; falls back to admin when omitted.
  isGlobalHolder?: boolean;
}) => {
  const t = useTranslations("common.isPublicSelector");
  const effectivePublicToWhom = publicToWhom ?? t("usersFallback.text");
  const { data: userGroups, isLoading: userGroupsIsLoading } = useUserGroups();
  const { isAdmin, user } = useUser();
  const businessTier = useTierAtLeast(Tier.BUSINESS);
  const canActGlobally = isGlobalHolder ?? isAdmin;

  // A scoped manager can only create non-public objects. Group selection stays
  // theirs to make — auto-assigning the org's only group and hiding the picker
  // was curator-era behaviour that silently scoped objects without consent.
  useEffect(() => {
    if (!user || !businessTier) return;
    if (!canActGlobally) {
      formikProps.setFieldValue("is_public", false);
    } else if (formikProps.values.is_public) {
      formikProps.setFieldValue("groups", []);
    }
  }, [user, userGroups, businessTier, canActGlobally]);

  if (userGroupsIsLoading) {
    return <div>{t("loading.text")}</div>;
  }
  if (!businessTier) {
    return null;
  }

  return (
    <div>
      {canActGlobally && (
        <>
          <BooleanFormField
            name="is_public"
            removeIndent={removeIndent}
            small={smallLabels}
            label={t("makePublic.label", { objectName })}
            subtext={
              <span className="block mt-2 text-sm text-text-600 dark:text-neutral-400">
                {t.rich("makePublic.subtext", {
                  objectName,
                  publicToWhom: effectivePublicToWhom,
                  b: (chunks) => <b>{chunks}</b>,
                })}
              </span>
            }
          />
        </>
      )}

      <GroupsMultiSelect
        formikProps={formikProps}
        label={t("assignGroups.label", { objectName })}
        subtext={
          canActGlobally || !enforceGroupSelection
            ? t("assignGroups.visibleSubtext", { objectName })
            : t("assignGroups.scopedSubtext", { objectName })
        }
        disabled={formikProps.values.is_public}
        disabledMessage={t("publicDisabled.message", { objectName })}
      />
    </div>
  );
};
