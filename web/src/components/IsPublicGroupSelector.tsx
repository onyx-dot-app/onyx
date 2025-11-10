import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";
import React, { useState, useEffect } from "react";
import { FormikProps } from "formik";
import { UserRole } from "@/lib/types";
import { useUserGroups } from "@/lib/hooks";
import { BooleanFormField } from "@/components/Field";
import { useUser } from "./user/UserProvider";
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
  publicToWhom = "Users",
  removeIndent = false,
  enforceGroupSelection = true,
  smallLabels = false,
}: {
  formikProps: FormikProps<T>;
  objectName: string;
  publicToWhom?: string;
  removeIndent?: boolean;
  enforceGroupSelection?: boolean;
  smallLabels?: boolean;
}) => {
  const { data: userGroups, isLoading: userGroupsIsLoading } = useUserGroups();
  const { isAdmin, user, isCurator } = useUser();
  const isPaidEnterpriseFeaturesEnabled = usePaidEnterpriseFeaturesEnabled();
  const [shouldHideContent, setShouldHideContent] = useState(false);

  useEffect(() => {
    if (user && userGroups && isPaidEnterpriseFeaturesEnabled) {
      const isUserAdmin = user.role === UserRole.ADMIN;
      if (!isUserAdmin && userGroups.length > 0) {
        formikProps.setFieldValue("is_public", false);
      }
      if (
        userGroups.length === 1 &&
        userGroups[0] !== undefined &&
        !isUserAdmin
      ) {
        formikProps.setFieldValue("groups", [userGroups[0].id]);
        setShouldHideContent(true);
      } else if (formikProps.values.is_public) {
        formikProps.setFieldValue("groups", []);
        setShouldHideContent(false);
      } else {
        setShouldHideContent(false);
      }
    }
  }, [user, userGroups, isPaidEnterpriseFeaturesEnabled]);

  if (userGroupsIsLoading) {
    return <div>Loading...</div>;
  }
  if (!isPaidEnterpriseFeaturesEnabled) {
    return null;
  }

  let firstUserGroupName = "Unknown";
  if (userGroups) {
    const userGroup = userGroups[0];
    if (userGroup) {
      firstUserGroupName = userGroup.name;
    }
  }

  if (shouldHideContent && enforceGroupSelection) {
    return (
      <>
        {userGroups && (
          <div className="mb-1 font-medium text-base">
            This {objectName} will be assigned to group{" "}
            <b>{firstUserGroupName}</b>.
          </div>
        )}
      </>
    );
  }

  return (
    <div>
      {isAdmin && (
        <>
          <BooleanFormField
            name="is_public"
            removeIndent={removeIndent}
            small={smallLabels}
            label={
              publicToWhom === "Curators"
                ? `Make this ${objectName} Curator Accessible?`
                : `Make this ${objectName} Public?`
            }
            disabled={!isAdmin}
            subtext={
              <span className="block mt-2 text-sm text-text-600 dark:text-neutral-400">
                If set, then this {objectName} will be usable by{" "}
                <b>All {publicToWhom}</b>. Otherwise, only <b>Admins</b> and{" "}
                <b>{publicToWhom}</b> who have explicitly been given access to
                this {objectName} (e.g. via a User Group) will have access.
              </span>
            }
          />
        </>
      )}

      <GroupsMultiSelect
        formikProps={formikProps}
        label={`Assign group access for this ${objectName}`}
        subtext={
          isAdmin || !enforceGroupSelection
            ? `This ${objectName} will be visible/accessible by the groups selected below`
            : `Curators must select one or more groups to give access to this ${objectName}`
        }
        disabled={formikProps.values.is_public && !isCurator}
        disabledMessage={`This ${objectName} is public and available to all users.`}
      />
    </div>
  );
};
