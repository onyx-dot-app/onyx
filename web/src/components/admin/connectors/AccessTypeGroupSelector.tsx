import { useTierAtLeast } from "@/hooks/useTierAtLeast";
import { Tier } from "@/lib/settings/types";
import React, { useEffect } from "react";
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
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import { Permission } from "@/lib/types";
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
  const { isScopedManager } = usePermissionAuthority(
    Permission.MANAGE_CONNECTORS
  );
  const businessTier = useTierAtLeast(Tier.BUSINESS);
  const isAutoSyncSupported = isValidAutoSyncSource(connector);

  const [access_type, meta, access_type_helpers] =
    useField<AccessType>("access_type");
  const [groups, groups_meta, groups_helpers] = useField<number[]>("groups");

  // A scoped manager can only create non-public connectors, so default them to
  // private. Group selection stays theirs to make — auto-assigning their only
  // group and hiding the control was curator-era behaviour, and it silently
  // scoped a connector for anyone who merely happened to be in one group.
  useEffect(() => {
    if (!businessTier) return;
    if (!access_type.value && isScopedManager && !isAutoSyncSupported) {
      access_type_helpers.setValue("private");
    }
    if (access_type.value === "public") {
      groups_helpers.setValue([]);
    }
  }, [
    access_type.value,
    access_type_helpers,
    groups_helpers,
    businessTier,
    isScopedManager,
    isAutoSyncSupported,
  ]);

  if (userGroupsIsLoading) {
    return null;
  }
  if (!businessTier) {
    return null;
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
                    : isScopedManager
                      ? "Select one or more of the groups you manage to give access to this Connector"
                      : "This Connector will be visible/accessible by the groups selected below"}
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
