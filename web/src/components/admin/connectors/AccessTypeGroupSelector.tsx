import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";
import React, { useState, useEffect } from "react";
import { FieldArray, ArrayHelpers, ErrorMessage, useField } from "formik";
import Text from "@/refresh-components/texts/Text";
import Button from "@/refresh-components/buttons/Button";
import Separator from "@/refresh-components/Separator";
import { UserGroup, UserRole } from "@/lib/types";
import { useUserGroups } from "@/lib/hooks";
import {
  AccessType,
  ValidAutoSyncSource,
  ConfigurableSources,
  validAutoSyncSources,
} from "@/lib/types";
import { useUser } from "@/components/user/UserProvider";
import { SvgUsers } from "@opal/icons";
function isValidAutoSyncSource(
  value: ConfigurableSources
): value is ValidAutoSyncSource {
  return validAutoSyncSources.includes(value as ValidAutoSyncSource);
}

// This should be included for all forms that require groups / public access
// to be set, and access to this / permissioning should be handled within this component itself.

export type AccessTypeGroupSelectorFormType = {
  access_type: AccessType;
  groups: number[];
};

export function AccessTypeGroupSelector({
  connector,
}: {
  connector: ConfigurableSources;
}) {
  const { data: userGroups, isLoading: userGroupsIsLoading } = useUserGroups();
  const { isAdmin, user, isCurator } = useUser();
  const isPaidEnterpriseFeaturesEnabled = usePaidEnterpriseFeaturesEnabled();
  const [shouldHideContent, setShouldHideContent] = useState(false);
  const isAutoSyncSupported = isValidAutoSyncSource(connector);

  const [access_type, meta, access_type_helpers] =
    useField<AccessType>("access_type");
  const [groups, groups_meta, groups_helpers] = useField<number[]>("groups");

  useEffect(() => {
    if (user && userGroups && isPaidEnterpriseFeaturesEnabled) {
      const isUserAdmin = user.role === UserRole.ADMIN;
      if (!isPaidEnterpriseFeaturesEnabled) {
        access_type_helpers.setValue("public");
        return;
      }

      // Only set default access type if it's not already set, to avoid overriding user selections
      if (!access_type.value && !isUserAdmin && !isAutoSyncSupported) {
        access_type_helpers.setValue("private");
      }

      if (
        access_type.value === "private" &&
        userGroups.length === 1 &&
        userGroups[0] !== undefined &&
        !isUserAdmin
      ) {
        groups_helpers.setValue([userGroups[0].id]);
        setShouldHideContent(true);
      } else if (access_type.value !== "private") {
        // If the access type is public or sync, empty the groups selection
        groups_helpers.setValue([]);
        setShouldHideContent(false);
      } else {
        setShouldHideContent(false);
      }
    }
  }, [
    user,
    userGroups,
    access_type.value,
    access_type_helpers,
    groups_helpers,
    isPaidEnterpriseFeaturesEnabled,
    isAutoSyncSupported,
  ]);

  if (userGroupsIsLoading) {
    return <div>Loading...</div>;
  }
  if (!isPaidEnterpriseFeaturesEnabled) {
    return null;
  }

  if (shouldHideContent) {
    return (
      <>
        {userGroups && userGroups[0] !== undefined && (
          <div className="mb-1 font-medium text-base">
            This Connector will be assigned to group <b>{userGroups[0].name}</b>
            .
          </div>
        )}
      </>
    );
  }

  return (
    <div>
      {(access_type.value === "private" || isCurator) &&
        userGroups &&
        userGroups?.length > 0 && (
          <>
            <Separator />
            <div className="flex flex-col gap-3 pt-4">
              <Text as="p" mainUiAction text05>
                Assign group access for this Connector
              </Text>
              {userGroupsIsLoading ? (
                <div className="animate-pulse bg-background-200 h-8 w-32 rounded" />
              ) : (
                <Text as="p" mainUiMuted text03>
                  {isAdmin
                    ? "This Connector will be visible/accessible by the groups selected below"
                    : "Curators must select one or more groups to give access to this Connector"}
                </Text>
              )}
            </div>
            <FieldArray
              name="groups"
              render={(arrayHelpers: ArrayHelpers) => (
                <div className="flex flex-wrap gap-2 py-4">
                  {userGroupsIsLoading ? (
                    <div className="animate-pulse bg-background-200 h-8 w-32 rounded"></div>
                  ) : (
                    userGroups &&
                    userGroups.map((userGroup: UserGroup) => {
                      const ind = groups.value.indexOf(userGroup.id);
                      let isSelected = ind !== -1;
                      return (
                        <Button
                          key={userGroup.id}
                          primary
                          action={isSelected}
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
}
