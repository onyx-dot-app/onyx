import React, { useState, useEffect } from "react";
import { FormikProps, FieldArray, ArrayHelpers, ErrorMessage } from "formik";
import { Text, Divider } from "@tremor/react";
import { FiUsers } from "react-icons/fi";
import { UserGroup, User, UserRole } from "@/lib/types";
import { useUserGroups } from "@/lib/hooks";
import { BooleanFormField } from "@/components/admin/connectors/Field";
import { useUser } from "./user/UserProvider";

export type IsPublicGroupSelectorFormType = {
  is_public: boolean;
  groups: number[];
};

export const IsPublicGroupSelector = <T extends IsPublicGroupSelectorFormType>({
  formikProps,
  objectName,
  enforceGroupSelection = true,
}: {
  formikProps: FormikProps<T>;
  objectName: string;
  enforceGroupSelection?: boolean;
}) => {
  const { data: userGroups, isLoading: userGroupsIsLoading } = useUserGroups();
  const { isAdmin, user, isLoadingUser } = useUser();
  const [shouldHideContent, setShouldHideContent] = useState(false);

  useEffect(() => {
    if (user && userGroups) {
      const isUserAdmin = user.role === UserRole.ADMIN;
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
  }, [
    user,
    userGroups,
    formikProps.setFieldValue,
    formikProps.values.is_public,
  ]);

  if (isLoadingUser || userGroupsIsLoading) {
    return <div>Loading...</div>;
  }

  if (shouldHideContent && enforceGroupSelection) {
    return (
      <>
        {userGroups && (
          <div className="mb-1 font-medium text-base">
            This {objectName} will be assigned to group{" "}
            <b>{userGroups[0].name}</b>.
          </div>
        )}
      </>
    );
  }

  return (
    <div>
      <Divider />
      {isAdmin && (
        <>
          <BooleanFormField
            name="is_public"
            label="Is Public?"
            disabled={!isAdmin}
            subtext={
              <span className="block mt-2 text-sm text-gray-500">
                If set, then this {objectName} will be visible to{" "}
                <b>all users</b>. If turned off, then only users who explicitly
                have been given access to this {objectName} (e.g. through a User
                Group) will have access.
              </span>
            }
          />
        </>
      )}

      {(!formikProps.values.is_public ||
        !isAdmin ||
        formikProps.values.groups.length > 0) && (
        <>
          <div className="flex gap-x-2 items-center">
            <div className="block font-medium text-base">
              Assign group access for this {objectName}
            </div>
          </div>
          <Text className="mb-3">
            {isAdmin || !enforceGroupSelection ? (
              <>
                This {objectName} will be visible/accessible by the groups
                selected below
              </>
            ) : (
              <>
                Curators must select one or more groups to give access to this{" "}
                {objectName}
              </>
            )}
          </Text>
          <FieldArray
            name="groups"
            render={(arrayHelpers: ArrayHelpers) => (
              <div className="flex gap-2 flex-wrap mb-4">
                {userGroupsIsLoading ? (
                  <div className="animate-pulse bg-gray-200 h-8 w-32 rounded"></div>
                ) : (
                  userGroups &&
                  userGroups.map((userGroup: UserGroup) => {
                    const ind = formikProps.values.groups.indexOf(userGroup.id);
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
                        ${isSelected ? "bg-background-strong" : "hover:bg-hover"}
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
                          <FiUsers className="my-auto mr-2" /> {userGroup.name}
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
