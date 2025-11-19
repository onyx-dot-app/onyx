import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";
import React, { useState, useEffect } from "react";
import { FormikProps, FieldArray, ArrayHelpers, ErrorMessage } from "formik";
import Text from "@/refresh-components/texts/Text";
import Button from "@/refresh-components/buttons/Button";
import { UserGroup, UserRole } from "@/lib/types";
import { useUserGroups } from "@/lib/hooks";
import { BooleanFormField } from "@/components/Field";
import { useUser } from "./user/UserProvider";
import SvgUsers from "@/icons/users";
import { cn } from "@/lib/utils";

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
}: {
  formikProps: FormikProps<T>;
  objectName: string;
  publicToWhom?: string;
  removeIndent?: boolean;
  enforceGroupSelection?: boolean;
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

      {(!formikProps.values.is_public || isCurator) &&
        userGroups &&
        userGroups?.length > 0 && (
          <>
            <div className="flex flex-col gap-3 pt-4">
              <Text mainUiAction text05>
                Assign group access for this {objectName}
              </Text>
              {userGroupsIsLoading ? (
                <div className="animate-pulse bg-background-200 h-8 w-32 rounded" />
              ) : (
                <Text mainUiMuted text03>
                  {isAdmin || !enforceGroupSelection ? (
                    <>
                      This {objectName} will be visible/accessible by the groups
                      selected below
                    </>
                  ) : (
                    <>
                      Curators must select one or more groups to give access to
                      this {objectName}
                    </>
                  )}
                </Text>
              )}
            </div>
            <FieldArray
              name="groups"
              render={(arrayHelpers: ArrayHelpers) => (
                <div className="flex flex-wrap gap-2 py-4">
                  {userGroupsIsLoading ? (
                    <div className="animate-pulse bg-background-200 h-8 w-32 rounded" />
                  ) : (
                    userGroups &&
                    userGroups.map((userGroup: UserGroup) => {
                      const ind = formikProps.values.groups.indexOf(
                        userGroup.id
                      );
                      const isSelected = ind !== -1;
                      return (
                        <Button
                          key={userGroup.id}
                          primary
                          action={isSelected}
                          type="button"
                          leftIcon={SvgUsers}
                          onClick={() => {
                            if (isSelected) {
                              arrayHelpers.remove(ind);
                            } else {
                              arrayHelpers.push(userGroup.id);
                            }
                          }}
                        >
                          {userGroup.name}
                        </Button>
                      );
                    })
                  )}
                </div>
              )}
            />
            <ErrorMessage
              name="groups"
              component="div"
              className="text-error text-sm mt-1"
            />
          </>
        )}
    </div>
  );
};
