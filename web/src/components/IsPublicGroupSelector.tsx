import i18n from "@/i18n/init";
import k from "./../i18n/keys";
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";
import React, { useState, useEffect } from "react";
import { FormikProps, FieldArray, ArrayHelpers, ErrorMessage } from "formik";
import Text from "@/components/ui/text";
import { FiUsers } from "react-icons/fi";
import { Separator } from "@/components/ui/separator";
import { UserGroup, UserRole } from "@/lib/types";
import { useUserGroups } from "@/lib/hooks";
import { BooleanFormField } from "@/components/admin/connectors/Field";
import { useUser } from "./user/UserProvider";

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
      if (!isUserAdmin) {
        formikProps.setFieldValue("is_public", false);
      }
      if (userGroups.length === 1 && !isUserAdmin) {
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
    return <div>{i18n.t(k.LOADING)}</div>;
  }
  if (!isPaidEnterpriseFeaturesEnabled) {
    return null;
  }

  if (shouldHideContent && enforceGroupSelection) {
    return (
      <>
        {userGroups && (
          <div className="mb-1 font-medium text-base">
            {i18n.t(k.THIS)} {objectName} {i18n.t(k.WILL_BE_ASSIGNED_TO_GROUP)}{" "}
            <b>{userGroups[0].name}</b>
            {i18n.t(k._8)}
          </div>
        )}
      </>
    );
  }

  return (
    <div>
      <Separator />
      {isAdmin && (
        <>
          <BooleanFormField
            name="is_public"
            removeIndent={removeIndent}
            label={
              publicToWhom === "Curators"
                ? `${i18n.t(k.MAKE_THIS)} ${objectName} ${i18n.t(
                    k.CURATOR_ACCESSIBLE
                  )}`
                : `${i18n.t(k.MAKE_THIS)} ${objectName} ${i18n.t(k.PUBLIC2)}`
            }
            disabled={!isAdmin}
            subtext={
              <span className="block mt-2 text-sm text-text-600 dark:text-neutral-400">
                {i18n.t(k.IF_SET_THEN_THIS)}{" "}
                {objectName === "document set"
                  ? "набор документов"
                  : objectName}{" "}
                {i18n.t(k.WILL_BE_USABLE_BY)}{" "}
                <b>
                  {i18n.t(k.ALL1)}{" "}
                  {publicToWhom === "Users" ? "пользователей" : publicToWhom}
                </b>
                {i18n.t(k.OTHERWISE_ONLY)} <b>{i18n.t(k.ADMINS)}</b>{" "}
                {i18n.t(k.AND)}{" "}
                <b>
                  {publicToWhom === "Users" ? "Пользователи" : publicToWhom}
                </b>{" "}
                {i18n.t(k.WHO_HAVE_EXPLICITLY_BEEN_GIVEN)}
                {objectName === "document set"
                  ? "набору документов"
                  : objectName}{" "}
                {i18n.t(k.E_G_VIA_A_USER_GROUP_WILL_H)}
              </span>
            }
          />
        </>
      )}

      {(!formikProps.values.is_public || isCurator) &&
        userGroups &&
        userGroups?.length > 0 && (
          <>
            <div className="flex mt-4 gap-x-2 items-center">
              <div className="block font-medium text-base">
                {i18n.t(k.ASSIGN_GROUP_ACCESS_FOR_THIS)} {objectName}
              </div>
            </div>
            {userGroupsIsLoading ? (
              <div className="animate-pulse bg-background-200 h-8 w-32 rounded"></div>
            ) : (
              <Text className="mb-3">
                {isAdmin || !enforceGroupSelection ? (
                  <>
                    {i18n.t(k.THIS)} {objectName}{" "}
                    {i18n.t(k.WILL_BE_VISIBLE_ACCESSIBLE_BY)}
                  </>
                ) : (
                  <>
                    {i18n.t(k.CURATORS_MUST_SELECT_ONE_OR_MO1)}
                    {objectName}
                  </>
                )}
              </Text>
            )}
            <FieldArray
              name="groups"
              render={(arrayHelpers: ArrayHelpers) => (
                <div className="flex gap-2 flex-wrap mb-4">
                  {userGroupsIsLoading ? (
                    <div className="animate-pulse bg-background-200 h-8 w-32 rounded"></div>
                  ) : (
                    userGroups &&
                    userGroups.map((userGroup: UserGroup) => {
                      const ind = formikProps.values.groups.indexOf(
                        userGroup.id
                      );
                      let isSelected = ind !== -1;
                      return (
                        <div
                          key={userGroup.id}
                          className={`
                        px-3 
                        py-1
                        rounded-lg 
                        border
                        border-border 
                        w-fit 
                        flex 
                        cursor-pointer 
                        ${
                          isSelected
                            ? "bg-background-200"
                            : "hover:bg-accent-background-hovered"
                        }
                      `}
                          onClick={() => {
                            if (isSelected) {
                              arrayHelpers.remove(ind);
                            } else {
                              arrayHelpers.push(userGroup.id);
                            }
                          }}
                        >
                          <div className="my-auto flex">
                            <FiUsers className="my-auto mr-2" />{" "}
                            {userGroup.name}
                          </div>
                        </div>
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
