"use client";

import { useTranslation } from "@/hooks/useTranslation";
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
  const { t } = useTranslation();
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
    return <div>{t(k.LOADING)}</div>;
  }
  if (!isPaidEnterpriseFeaturesEnabled) {
    return null;
  }

  if (shouldHideContent && enforceGroupSelection) {
    return (
      <>
        {userGroups && (
          <div className="mb-1 font-medium text-base">
            {t(k.THIS)} {objectName} {t(k.WILL_BE_ASSIGNED_TO_GROUP)}{" "}
            <b>{userGroups[0].name}</b>
            {t(k._8)}
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
                ? `${t(k.MAKE_THIS)} ${
                    objectName === "document set"
                      ? "t(k.DOCUMENT_SET)"
                      : objectName
                  } ${t(k.CURATOR_ACCESSIBLE)}`
                : `${t(k.MAKE_THIS)} ${
                    objectName === "document set"
                      ? "t(k.DOCUMENT_SET)"
                      : objectName
                  } ${t(k.PUBLIC2)}`
            }
            disabled={!isAdmin}
            subtext={
              <span className="block mt-2 text-sm text-text-600 dark:text-neutral-400">
                {t(k.IF_SET_THEN_THIS)}{" "}
                {objectName === "document set"
                  ? "t(k.DOCUMENT_SET)"
                  : objectName}{" "}
                {t(k.WILL_BE_USABLE_BY)}{" "}
                <b>
                  {t(k.ALL1)}{" "}
                  {publicToWhom === "Users" ? t(k.USERS) : publicToWhom}
                </b>
                {t(k.OTHERWISE_ONLY)} <b>{t(k.ADMINS)}</b> {t(k.AND)}{" "}
                <b>
                  {publicToWhom === "Users" ? t(k.USERS_CAPITAL) : publicToWhom}
                </b>
                {", "}
                {t(k.WHO_HAVE_EXPLICITLY_BEEN_GIVEN)}{" "}
                {objectName === "document set"
                  ? t(k.TO_DOCUMENT_SET)
                  : objectName}{" "}
                {t(k.E_G_VIA_A_USER_GROUP_WILL_H)}
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
                {t(k.ASSIGN_GROUP_ACCESS_FOR_THIS)}{" "}
                {objectName === "document set"
                  ? t(k.OF_DOCUMENT_SETS)
                  : objectName}
              </div>
            </div>
            {userGroupsIsLoading ? (
              <div className="animate-pulse bg-background-200 h-8 w-32 rounded"></div>
            ) : (
              <Text className="mb-3">
                {isAdmin || !enforceGroupSelection ? (
                  <>
                    {t(k.THIS)}{" "}
                    {objectName === "document set"
                      ? "t(k.DOCUMENT_SET)"
                      : objectName}{" "}
                    {t(k.WILL_BE_VISIBLE_ACCESSIBLE_BY)}
                  </>
                ) : (
                  <>
                    {t(k.CURATORS_MUST_SELECT_ONE_OR_MO1)}
                    {objectName === "document set"
                      ? "t(k.DOCUMENT_SET)"
                      : objectName}
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
