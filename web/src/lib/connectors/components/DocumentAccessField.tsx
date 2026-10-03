"use client";

import { useEffect, useMemo, useRef } from "react";
import { useField } from "formik";
import { useTranslations } from "next-intl";
import { InputSingleSelect, type SelectOption } from "@opal/components";
import { InputHorizontal, Section } from "@opal/layouts";
import { SvgOrganization, SvgUserSync, SvgUsers } from "@opal/icons";
import { AccessType, Permission } from "@/lib/types";
import {
  ValidAutoSyncSource,
  ConfigurableSources,
  validAutoSyncSources,
} from "@/lib/connectors/types/source";
import { AutoSyncOptions } from "@/components/admin/connectors/AutoSyncOptions";
import { ConnectorGroupRestrictionPicker } from "@/sections/connectors/ConnectorGroupRestrictionPicker";
import { useConnectorGroupRestrictionsEnabled } from "@/lib/connectors/hooks";
import GroupShareList from "@/lib/connectors/components/GroupShareList";
import { useTierAtLeast } from "@/hooks/useTierAtLeast";
import { Tier } from "@/lib/settings/types";
import type { Credential } from "@/lib/credentials/types";
import { getCredentialSpec } from "@/lib/credentials/utils";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import { useSettings } from "@/lib/settings/hooks";
import { getSourceDisplayName } from "@/lib/sources";

function isValidAutoSyncSource(
  value: ConfigurableSources
): value is ValidAutoSyncSource {
  return validAutoSyncSources.includes(value as ValidAutoSyncSource);
}

interface DocumentAccessFieldProps {
  connector: ConfigurableSources;
  currentCredential?: Credential<any> | null;
  disabled?: boolean;
}

/**
 * Who can read the connector's documents: synced from the source, specific
 * groups (private, with a group picker), or everyone (public). Renders nothing
 * below the Business tier, where every connector is public.
 */
export default function DocumentAccessField({
  connector,
  currentCredential,
  disabled,
}: DocumentAccessFieldProps) {
  const t = useTranslations("admin.connectorsList.settings.documentAccess");
  const tRestriction = useTranslations("admin.connector.groupRestriction");
  const { appName } = useSettings();
  const [accessType, , accessTypeHelpers] = useField<AccessType>("access_type");
  const { isScopedManager } = usePermissionAuthority(
    Permission.MANAGE_CONNECTORS
  );

  // Private requires User Groups, Auto Sync requires permission-sync —
  // both are Business+ features.
  const businessTier = useTierAtLeast(Tier.BUSINESS);
  const showAutoSync = businessTier && isValidAutoSyncSource(connector);
  const groupRestrictionsEnabled = useConnectorGroupRestrictionsEnabled();

  const selectedAuthMethod = currentCredential?.credential_json?.[
    "authentication_method"
  ] as string | undefined;

  const isSyncDisabledByAuth = useMemo(() => {
    const authMethods = getCredentialSpec(connector)?.methods;
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

  const options = useMemo(() => {
    const built: SelectOption[] = [];
    if (showAutoSync) {
      built.push({
        value: "sync",
        title: t("sync.title", {
          source: getSourceDisplayName(connector) ?? connector,
        }),
        description: isSyncDisabledByAuth
          ? t("sync.disabledReason")
          : t("sync.description", { appName }),
        icon: SvgUserSync,
        disabled: isSyncDisabledByAuth,
      });
    }
    if (businessTier) {
      built.push({
        value: "private",
        title: t("specificGroups.title"),
        description: t("specificGroups.description"),
        icon: SvgUsers,
      });
    }
    // A scoped manager's authority stops at the groups they manage, so the
    // backend rejects a public connector from them. Offering it would only
    // produce a 403 on submit.
    if (!isScopedManager) {
      built.push({
        value: "public",
        title: t("everyone.title"),
        description: t("everyone.description"),
        icon: SvgOrganization,
      });
    }
    return built;
  }, [
    businessTier,
    isScopedManager,
    showAutoSync,
    isSyncDisabledByAuth,
    connector,
    t,
    appName,
  ]);

  // Sync is the default wherever it is offered and enabled, until the user
  // picks an option themselves.
  const userChoseRef = useRef(false);
  const syncAvailable = showAutoSync && !isSyncDisabledByAuth;
  useEffect(() => {
    if (userChoseRef.current || !syncAvailable) return;
    if (accessType.value !== "sync") accessTypeHelpers.setValue("sync");
  }, [syncAvailable, accessType.value, accessTypeHelpers]);

  // Move off an access type the user is not offered, or that is disabled.
  useEffect(() => {
    if (!businessTier || !options.length) return;
    if (
      options.some(
        (option) => option.value === accessType.value && !option.disabled
      )
    )
      return;
    const fallback =
      options.find(
        (option) => option.value === defaultAccess && !option.disabled
      ) ?? options.find((option) => !option.disabled);
    if (fallback) accessTypeHelpers.setValue(fallback.value as AccessType);
  }, [
    businessTier,
    options,
    defaultAccess,
    accessType.value,
    accessTypeHelpers,
  ]);

  if (!businessTier) return null;

  return (
    <Section gap={3} alignItems="stretch" height="fit">
      <InputHorizontal
        withLabel="access_type"
        title={t("title")}
        description={t("description")}
        disabled={disabled}
        fillInput
        center
      >
        <InputSingleSelect
          id="access_type"
          value={accessType.value}
          onValueChange={(value) => {
            // A re-pick emits "": the pick stands.
            const option = options.find((o) => o.value === value);
            if (!option) return;
            userChoseRef.current = true;
            accessTypeHelpers.setValue(option.value as AccessType);
          }}
          options={options}
          placeholder={t("title")}
          disabled={disabled}
        />
      </InputHorizontal>

      {accessType.value === "private" && (
        <GroupShareList
          name="data_access_group_ids"
          placeholder={tRestriction("picker.placeholder")}
          disabled={disabled}
        />
      )}

      {accessType.value === "sync" &&
        showAutoSync &&
        groupRestrictionsEnabled && <ConnectorGroupRestrictionPicker />}
      {accessType.value === "sync" && showAutoSync && (
        <AutoSyncOptions connectorType={connector as ValidAutoSyncSource} />
      )}
    </Section>
  );
}
