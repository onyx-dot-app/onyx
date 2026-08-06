import { useTierAtLeast } from "@/hooks/useTierAtLeast";
import { Tier } from "@/lib/settings/types";
import React, { useState, useEffect } from "react";
import { FieldArray, ArrayHelpers, ErrorMessage, useField } from "formik";
import Text from "@/refresh-components/texts/Text";
import { Button, Divider } from "@opal/components";
import { UserGroup } from "@/lib/types";
import { useUserGroups } from "@/lib/hooks";
import {
  AccessType,
  ValidAutoSyncSource,
  ConfigurableSources,
  validAutoSyncSources,
} from "@/lib/types";
import { useUser } from "@/providers/UserProvider";
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
  const { isAdmin, user } = useUser();
  const businessTier = useTierAtLeast(Tier.BUSINESS);
  const [shouldHideContent, setShouldHideContent] = useState(false);
  const isAutoSyncSupported = isValidAutoSyncSource(connector);

  const [access_type, meta, access_type_helpers] =
    useField<AccessType>("access_type");
  const [groups, groups_meta, groups_helpers] = useField<number[]>("groups");

  useEffect(() => {
    if (user && userGroups && businessTier) {
      const isUserAdmin = isAdmin;
      if (!businessTier) {
        access_type_helpers.setValue("public");
        return;
      }

      // Only set default access type if it's not already set, to avoid overriding user selections
      if (!access_type.value && !isUserAdmin && !isAutoSyncSupported) {
        access_type_helpers.setValue("private");
      }

      // Groups apply to private (they grant document access) and to sync (they
      // scope who may *manage* the connector; the source still decides who can
      // read its documents). Public connectors have nothing to scope.
      const usesGroups =
        access_type.value === "private" || access_type.value === "sync";

      if (
        usesGroups &&
        userGroups.length === 1 &&
        userGroups[0] !== undefined &&
        !isUserAdmin
      ) {
        groups_helpers.setValue([userGroups[0].id]);
        setShouldHideContent(true);
      } else if (access_type.value === "public") {
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
    businessTier,
    isAutoSyncSupported,
  ]);

  if (userGroupsIsLoading) {
    return null;
  }
  if (!businessTier) {
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
      {(access_type.value === "private" || access_type.value === "sync") &&
        userGroups &&
        userGroups?.length > 0 && (
          <>
            <Divider />
            <div className="flex flex-col gap-3 pt-4">
              <Text as="p" mainUiAction text05>
                {access_type.value === "sync"
                  ? "Assign this Connector to a group"
                  : "Assign group access for this Connector"}
              </Text>
              {userGroupsIsLoading ? (
                <div className="animate-pulse bg-background-200 h-8 w-32 rounded-sm" />
              ) : (
                <Text as="p" mainUiMuted text03>
                  {access_type.value === "sync"
                    ? // Groups never widen or narrow a synced connector's document
                      // access — the source system's permissions decide that.
                      "The groups below control who can manage this Connector. Access to its documents is inherited from the source's own permissions."
                    : isAdmin
                      ? "This Connector will be visible/accessible by the groups selected below"
                      : "Group managers must select one or more groups to give access to this Connector"}
                </Text>
              )}
            </div>
            <FieldArray
              name="groups"
              render={(arrayHelpers: ArrayHelpers) => (
                <div className="flex flex-wrap gap-2 py-4">
                  {userGroupsIsLoading ? (
                    <div className="animate-pulse bg-background-200 h-8 w-32 rounded-sm"></div>
                  ) : (
                    userGroups &&
                    userGroups.map((userGroup: UserGroup) => {
                      const ind = groups.value.indexOf(userGroup.id);
                      let isSelected = ind !== -1;
                      return (
                        <Button
                          variant={isSelected ? "action" : "default"}
                          key={userGroup.id}
                          icon={SvgUsers}
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
