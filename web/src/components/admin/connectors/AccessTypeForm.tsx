import { DefaultDropdown } from "@/components/Dropdown";
import {
  AccessType,
  ValidAutoSyncSource,
  ConfigurableSources,
  validAutoSyncSources,
} from "@/lib/types";
import { useField } from "formik";
import { useTranslations } from "next-intl";
import { AutoSyncOptions } from "./AutoSyncOptions";
import { useTierAtLeast } from "@/hooks/useTierAtLeast";
import { Tier } from "@/lib/settings/types";
import { useEffect, useMemo } from "react";
import { Credential } from "@/lib/connectors/credentials";
import { credentialTemplates } from "@/lib/connectors/credentials";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import { Permission } from "@/lib/types";

function isValidAutoSyncSource(
  value: ConfigurableSources
): value is ValidAutoSyncSource {
  return validAutoSyncSources.includes(value as ValidAutoSyncSource);
}

export function AccessTypeForm({
  connector,
  currentCredential,
}: {
  connector: ConfigurableSources;
  currentCredential?: Credential<any> | null;
}) {
  const t = useTranslations("admin.connector.accessType");
  const [access_type, meta, access_type_helpers] =
    useField<AccessType>("access_type");
  const { isScopedManager } = usePermissionAuthority(
    Permission.MANAGE_CONNECTORS
  );

  // Private requires User Groups, Auto Sync requires permission-sync —
  // both are Business+ features.
  const businessTier = useTierAtLeast(Tier.BUSINESS);
  const showAutoSync = businessTier && isValidAutoSyncSource(connector);

  const selectedAuthMethod = currentCredential?.credential_json?.[
    "authentication_method"
  ] as string | undefined;

  // If the selected auth method is one that disables sync, return true
  const isSyncDisabledByAuth = useMemo(() => {
    const template = (credentialTemplates as any)[connector];
    const authMethods = template?.authMethods as
      | { value: string; disablePermSync?: boolean }[]
      | undefined; // auth methods are returned as an array of objects with a value and disablePermSync property
    if (!authMethods || !selectedAuthMethod) return false;
    const method = authMethods.find((m) => m.value === selectedAuthMethod);
    return method?.disablePermSync === true;
  }, [connector, selectedAuthMethod]);

  // Prefer Auto Sync when available, else Private (User Groups), else
  // Public. Mirrors the option-availability rules below.
  const defaultAccess: AccessType = showAutoSync
    ? "sync"
    : businessTier || isScopedManager
      ? "private"
      : "public";

  // Build options in display order: Private, Public, Auto Sync.
  const options = useMemo(() => {
    const built: {
      name: string;
      value: string;
      description: string;
      disabled: boolean;
      disabledReason: string;
    }[] = [];

    if (businessTier) {
      built.push({
        name: t("privateOption.name"),
        value: "private",
        description: t("privateOption.description"),
        disabled: false,
        disabledReason: "",
      });
    }

    // A scoped manager's authority stops at the groups they manage, so GATE 2
    // rejects a public connector outright (`within_scope` requires non-public).
    // Offering the option would only produce a 403 on submit.
    if (!isScopedManager) {
      built.push({
        name: t("publicOption.name"),
        value: "public",
        description: t("publicOption.description"),
        disabled: false,
        disabledReason: "",
      });
    }

    if (showAutoSync) {
      built.push({
        name: t("autoSyncOption.name"),
        value: "sync",
        description: t("autoSyncOption.description"),
        disabled: isSyncDisabledByAuth,
        disabledReason: t("autoSyncOption.disabledReason"),
      });
    }

    return built;
  }, [businessTier, isScopedManager, showAutoSync, isSyncDisabledByAuth, t]);

  useEffect(() => {
    if (!businessTier || !options.length) return;
    if (options.some((option) => option.value === access_type.value)) return;
    const fallback =
      options.find(
        (option) => option.value === defaultAccess && !option.disabled
      ) ?? options.find((option) => !option.disabled);
    if (fallback) access_type_helpers.setValue(fallback.value as AccessType);
  }, [
    businessTier,
    options,
    defaultAccess,
    access_type.value,
    access_type_helpers,
  ]);

  if (!businessTier) return null;

  return (
    <>
      <div>
        <p className="text-text-950 font-medium">{t("heading.title")}</p>
        <p className="text-sm text-text-500">{t("heading.description")}</p>
      </div>
      <DefaultDropdown
        options={options}
        selected={access_type.value}
        onSelect={(selected) =>
          access_type_helpers.setValue(selected as AccessType)
        }
        includeDefault={false}
      />
      {access_type.value === "sync" && showAutoSync && (
        <AutoSyncOptions connectorType={connector as ValidAutoSyncSource} />
      )}
    </>
  );
}
