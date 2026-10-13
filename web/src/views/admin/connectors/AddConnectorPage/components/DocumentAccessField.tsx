"use client";

import { useEffect, useMemo, useRef } from "react";
import { useField } from "formik";
import { useTranslations } from "next-intl";
import { InputSingleSelect, type SelectOption } from "@opal/components";
import {
  usePlans,
  useTierAtLeast,
  useTierLockedOptions,
} from "@/lib/tiers/hooks";
import { InputHorizontal, Section } from "@opal/layouts";
import { SvgOrganization, SvgUserSync, SvgUsers } from "@opal/icons";
import { AccessType, Permission } from "@/lib/types";
import {
  ValidAutoSyncSource,
  ConfigurableSources,
  validAutoSyncSources,
} from "@/lib/connectors/types/source";
import AutoSyncOptions from "@/views/admin/connectors/AddConnectorPage/components/AutoSyncOptions";
import ConnectorGroupRestrictionPicker from "@/lib/connectors/components/ConnectorGroupRestrictionPicker";
import { useConnectorGroupRestrictionsEnabled } from "@/lib/connectors/hooks";
import GroupShareList from "@/lib/connectors/components/GroupShareList";
import { Tier } from "@/lib/tiers/types";
import type { CredentialValues } from "@/lib/credentials/types";
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
  currentCredential?: CredentialValues | null;
  disabled?: boolean;
}

/**
 * Who can read the connector's documents: synced from the source, specific
 * groups (private, with a group picker), or everyone (public). Below the
 * Business tier every connector is public: the field still shows, locked on
 * Everyone, with the Business plan tag.
 */
export default function DocumentAccessField({
  connector,
  currentCredential,
  disabled,
}: DocumentAccessFieldProps) {
  const t = useTranslations("admin.connectorsList.settings.documentAccess");
  const tRestriction = useTranslations("admin.connector.groupRestriction");
  const { appName } = useSettings();
  const plans = usePlans();
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

  // Auto Sync and Specific Groups need Business; Everyone is on every tier.
  const businessOptions = useMemo(() => {
    const built: SelectOption[] = [];
    if (isValidAutoSyncSource(connector)) {
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
    built.push({
      value: "private",
      title: t("specificGroups.title"),
      description: t("specificGroups.description"),
      icon: SvgUsers,
    });
    return built;
  }, [isSyncDisabledByAuth, connector, t, appName]);
  // A scoped manager's authority stops at the groups they manage, so the
  // backend rejects a public connector from them. Offering it would only
  // produce a 403 on submit.
  const everyTierOptions = useMemo(
    (): SelectOption[] =>
      isScopedManager
        ? []
        : [
            {
              value: "public",
              title: t("everyone.title"),
              description: t("everyone.description"),
              icon: SvgOrganization,
            },
          ],
    [isScopedManager, t]
  );
  // What can be picked: below Business, only Everyone, which is the value.
  const options = useMemo(
    () =>
      businessTier
        ? [...everyTierOptions, ...businessOptions]
        : everyTierOptions,
    [businessTier, businessOptions, everyTierOptions]
  );
  // What the list shows: every option in one order. Below Business they all
  // sit locked under an upgrade link, Everyone selected.
  const lockForBusiness = useTierLockedOptions(Tier.BUSINESS);
  const listedOptions = useMemo(
    () => lockForBusiness([...everyTierOptions, ...businessOptions]),
    [everyTierOptions, businessOptions, lockForBusiness]
  );

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

  return (
    <Section gap={3} alignItems="stretch" height="fit">
      <InputHorizontal
        withLabel="access_type"
        title={t("title")}
        description={t("description")}
        tag={businessTier ? undefined : plans[Tier.BUSINESS].tag}
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
          options={listedOptions}
          placeholder={t("title")}
          disabled={disabled}
        />
      </InputHorizontal>

      {accessType.value === "private" && (
        <GroupShareList
          name="data_access_group_ids"
          label={t("specificGroups.title")}
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
