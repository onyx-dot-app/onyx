"use client";

import { useTranslation } from "@/hooks/useTranslation";
import k from "./../../../i18n/keys";
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
  const { t } = useTranslation();
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
      name: t(k.PRIVATE),
      value: "private",
      description: t(k.PRIVATE_DESCRIPTION),
    },
  ];

  if (isAdmin) {
    options.push({
      name: t(k.PUBLIC),
      value: "public",
      description: t(k.PUBLIC_DESCRIPTION),
    });
  }

  if (isAutoSyncSupported && isPaidEnterpriseEnabled) {
    options.push({
      name: t(k.AUTO_SYNC_PERMISSIONS),
      value: "sync",
      description: t(k.AUTO_SYNC_DESCRIPTION),
    });
  }

  return (
    <>
      {isPaidEnterpriseEnabled && (isAdmin || isAutoSyncSupported) && (
        <>
          <div>
            <label className="text-text-950 font-medium">
              {t(k.DOCUMENT_ACCESS)}
            </label>
            <p className="text-sm text-text-500">
              {t(k.CONTROL_WHO_HAS_ACCESS_TO_THE)}
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
