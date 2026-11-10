"use client";

import { useState } from "react";
import { useSWRConfig } from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import { useTranslations } from "next-intl";
import {
  Button,
  InputSingleComboBox,
  InputSingleSelect,
  Text,
} from "@opal/components";
import { InputVertical, Section } from "@opal/layouts";
import { SvgUsers } from "@opal/icons";
import useShareableGroups from "@/hooks/useShareableGroups";
import { useInstallationPolicyOptions } from "@/lib/skills/hooks";
import type { useCompanyMarketplaceAccess } from "@/lib/marketplaces/hooks";
import { SharePermissionMenu } from "@/lib/permissions/components";
import {
  useSharePermissionOptions,
  useShareScopeOptions,
} from "@/sections/modals/shareAccessConstants";

interface CompanyMarketplaceAccessControlsProps {
  access: ReturnType<typeof useCompanyMarketplaceAccess>;
  disabled?: boolean;
}

export default function CompanyMarketplaceAccessControls({
  access,
  disabled = false,
}: CompanyMarketplaceAccessControlsProps) {
  const t = useTranslations("marketplaces.access");
  const shared = useTranslations("skills.modals.share");
  const common = useTranslations("marketplaces");
  const permissionOptions = useSharePermissionOptions();
  const scopeOptions = useShareScopeOptions();
  const { data: groups, isLoading, error } = useShareableGroups();
  const { mutate } = useSWRConfig();
  const { draft, setDraft, status, ready } = access;
  const [lastPublicPermission, setLastPublicPermission] = useState(
    draft.public_permission ?? "VIEWER"
  );
  const paid = status === "paid";
  const locked = disabled || !ready;
  const installationOptions = useInstallationPolicyOptions();
  const policies = installationOptions.map(
    ({ value, label, description, icon }) => ({
      value,
      title: label,
      description,
      icon,
    })
  );

  return (
    <Section height="auto" alignItems="stretch" gap={4}>
      <Text font="secondary-body" color="text-03">
        {t("description")}
      </Text>
      {status === "forbidden" && <Text role="alert">{t("forbidden")}</Text>}
      {status === "loading" && <Text role="status">{t("loading")}</Text>}
      {status === "error" && (
        <Section height="auto" alignItems="start" gap={2}>
          <Text role="alert">{t("settingsError")}</Text>
          <Button
            prominence="secondary"
            disabled={disabled}
            onClick={access.refreshSettings}
          >
            {common("retry")}
          </Button>
        </Section>
      )}
      {status === "community" && (
        <Text role="status">{t(ready ? "community" : "restricted")}</Text>
      )}
      <InputVertical title={shared("accessTitle")}>
        <Section
          flexDirection="row"
          justifyContent="start"
          wrap
          height="auto"
          gap={2}
        >
          <InputSingleSelect
            placeholder={shared("scopeMenu.ariaLabel")}
            value={draft.public_permission === null ? "PRIVATE" : "PUBLIC"}
            defaultOption="PUBLIC"
            options={scopeOptions.map(({ value, label, icon }) => ({
              value,
              title: label,
              icon,
            }))}
            disabled={locked || !paid}
            onValueChange={(scope) => {
              if (scope === "PUBLIC" || scope === "PRIVATE") {
                if (draft.public_permission !== null)
                  setLastPublicPermission(draft.public_permission);
                setDraft({
                  ...draft,
                  public_permission:
                    scope === "PUBLIC"
                      ? (draft.public_permission ?? lastPublicPermission)
                      : null,
                });
              }
            }}
          />
          {draft.public_permission !== null && (
            <SharePermissionMenu
              ariaLabel={shared("organizationPermissionMenu.ariaLabel")}
              value={draft.public_permission}
              options={permissionOptions}
              disabled={locked || !paid}
              onChange={(permission) =>
                setDraft({ ...draft, public_permission: permission })
              }
            />
          )}
        </Section>
      </InputVertical>
      <InputVertical
        title={shared("installation.title")}
        description={t("installationDescription")}
      >
        <InputSingleSelect
          placeholder={shared("installation.title")}
          options={policies}
          value={draft.installation_policy}
          defaultOption="AVAILABLE"
          disabled={locked}
          onValueChange={(policy) => {
            const option = installationOptions.find(
              ({ value }) => value === policy
            );
            if (option)
              setDraft({ ...draft, installation_policy: option.value });
          }}
        />
        <Text font="secondary-body" color="text-03" role="status">
          {policies.find((policy) => policy.value === draft.installation_policy)
            ?.description ?? ""}
        </Text>
      </InputVertical>
      <InputVertical title={t("groups")}>
        {paid && (
          <>
            <InputSingleComboBox
              value=""
              placeholder={t("addGroup")}
              disabled={locked || isLoading || !!error}
              options={(groups ?? [])
                .filter(
                  (group) =>
                    !draft.group_shares.some(
                      (share) => share.group_id === group.id
                    )
                )
                .map((group) => ({
                  value: String(group.id),
                  title: group.name,
                  icon: SvgUsers,
                }))}
              onValueChange={(value) => {
                const group = groups?.find(
                  (candidate) => String(candidate.id) === value
                );
                if (
                  !group ||
                  draft.group_shares.some(
                    (share) => share.group_id === group.id
                  )
                )
                  return;
                setDraft({
                  ...draft,
                  group_shares: [
                    ...draft.group_shares,
                    {
                      group_id: group.id,
                      permission: "VIEWER",
                      installation_policy: null,
                    },
                  ],
                });
              }}
            />
            {isLoading && <Text role="status">{t("groupsLoading")}</Text>}
            {!!error && (
              <Section height="auto" alignItems="start" gap={2}>
                <Text role="alert">{t("groupsError")}</Text>
                <Button
                  prominence="secondary"
                  disabled={disabled}
                  onClick={() => void mutate(SWR_KEYS.shareableGroups)}
                >
                  {common("retry")}
                </Button>
              </Section>
            )}
          </>
        )}
        {draft.group_shares.map((share) => {
          const name =
            groups?.find((group) => group.id === share.group_id)?.name ??
            t("unknownGroup", { id: share.group_id });
          return (
            <Section
              key={share.group_id}
              role="group"
              aria-label={name}
              flexDirection="row"
              justifyContent="between"
              wrap
              height="auto"
              gap={2}
            >
              <Section
                width="auto"
                height="auto"
                alignItems="start"
                className="min-w-0 grow basis-40"
              >
                <Text wordWrap="wrap-anywhere">{name}</Text>
              </Section>
              <SharePermissionMenu
                ariaLabel={t("groupPermission", { name })}
                value={share.permission}
                options={permissionOptions}
                disabled={locked || !paid}
                onChange={(permission) =>
                  setDraft({
                    ...draft,
                    group_shares: draft.group_shares.map((current) =>
                      current.group_id === share.group_id
                        ? { ...current, permission }
                        : current
                    ),
                  })
                }
                onRemove={() =>
                  setDraft({
                    ...draft,
                    group_shares: draft.group_shares.filter(
                      (current) => current.group_id !== share.group_id
                    ),
                  })
                }
              />
            </Section>
          );
        })}
      </InputVertical>
    </Section>
  );
}
