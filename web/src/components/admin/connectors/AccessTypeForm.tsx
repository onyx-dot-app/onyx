import { DefaultDropdown } from "@/components/Dropdown";
import {
  AccessType,
  ValidAutoSyncSource,
  ConfigurableSources,
  validAutoSyncSources,
} from "@/lib/types";
import { useUser } from "@/components/user/UserProvider";
import { useField } from "formik";
import { AutoSyncOptions } from "./AutoSyncOptions";
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";
import { useEffect } from "react";

function isValidAutoSyncSource(
  value: ConfigurableSources
): value is ValidAutoSyncSource {
  return validAutoSyncSources.includes(value as ValidAutoSyncSource);
}

export function AccessTypeForm({
  connector,
}: {
  connector: ConfigurableSources;
}) {
  const [access_type, meta, access_type_helpers] =
    useField<AccessType>("access_type");

  const isPaidEnterpriseEnabled = usePaidEnterpriseFeaturesEnabled();
  const isAutoSyncSupported = isValidAutoSyncSource(connector);
  const { isAdmin } = useUser();

  useEffect(
    () => {
      // Only set default value if access_type.value is not already set
      if (!access_type.value) {
        if (!isPaidEnterpriseEnabled) {
          access_type_helpers.setValue("public");
        } else if (isAutoSyncSupported) {
          access_type_helpers.setValue("sync");
        } else {
          access_type_helpers.setValue("private");
        }
      }
    },
    [
      // Only run this effect once when the component mounts
      // eslint-disable-next-line react-hooks/exhaustive-deps
    ]
  );

  const options = [
    {
      name: "Private",
      value: "private",
      description:
        "Only users who have explicitly been given access to this connector (through the User Groups page) can access the documents pulled in by this connector",
    },
  ];

  if (isAdmin) {
    options.push({
      name: "Public",
      value: "public",
      description:
        "Everyone with an account on Onyx can access the documents pulled in by this connector",
    });
  }

  if (isAutoSyncSupported && isPaidEnterpriseEnabled) {
    options.push({
      name: "Auto Sync Permissions",
      value: "sync",
      description:
        "We will automatically sync permissions from the source. A document will be searchable in Onyx if and only if the user performing the search has permission to access the document in the source.",
    });
  }

  return (
    <>
      {isPaidEnterpriseEnabled && (isAdmin || isAutoSyncSupported) && (
        <>
          <div>
            <label className="text-text-950 font-medium">Document Access</label>
            <p className="text-sm text-text-500">
              Control who has access to the documents indexed by this connector.
            </p>
          </div>
          <DefaultDropdown
            options={options}
            selected={access_type.value}
            onSelect={(selected) =>
              access_type_helpers.setValue(selected as AccessType)
            }
            includeDefault={false}
          />
          {access_type.value === "sync" && isAutoSyncSupported && (
            <AutoSyncOptions connectorType={connector as ValidAutoSyncSource} />
          )}
        </>
      )}
    </>
  );
}
