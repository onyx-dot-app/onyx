"use client";

import { useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import useSWR from "swr";
import {
  Button,
  Card,
  Collapsible,
  Divider,
  Tag,
  Text,
} from "@opal/components";
import { Content, ContentAction, Section } from "@opal/layouts";
import {
  SvgEditBig,
  SvgOrganization,
  SvgShare,
  SvgUserManage,
  SvgUsers,
  SvgUserSync,
} from "@opal/icons";
import { IconLoader } from "@opal/loaders";
import type { IconFunctionComponent } from "@opal/types";
import { markdown } from "@opal/utils";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { useUserGroups } from "@/lib/hooks";
import { SWR_KEYS } from "@/lib/swr-keys";
import type {
  CCPairDataAccess,
  CCPairFullInfo,
  CCPairManageAccessRow,
} from "@/lib/connectors/types";
import { usesDataAccessGroups } from "@/lib/connectors/edit/prefill";
import { getSourceDisplayName } from "@/lib/connectors/utils";
import { useTierAtLeast } from "@/lib/tiers/hooks";
import { Tier } from "@/lib/tiers/types";

interface DocumentAccess {
  icon: IconFunctionComponent;
  label: string;
  summary: string;
}

export interface SharingSettingsSectionProps {
  ccPair: CCPairFullInfo;
  /** Shows the edit action, which opens the connector form. `null` hides it. */
  onEdit: (() => void) | null;
}

/** Who reads the connector's documents, and which groups manage it. */
export default function SharingSettingsSection({
  ccPair,
  onEdit,
}: SharingSettingsSectionProps) {
  const t = useTranslations("admin.connector.sharing");
  const [open, setOpen] = useState(false);
  const tSettings = useTranslations("admin.connectorsList.settings");
  const tGroups = useTranslations("admin.connector.groupRestriction");
  const format = useFormatter();
  const source = getSourceDisplayName(ccPair.connector.source) ?? "";
  const usesGroups = usesDataAccessGroups(ccPair.access_type);
  const { data: dataAccess, error: dataAccessError } = useSWR<CCPairDataAccess>(
    usesGroups ? SWR_KEYS.ccPairDataAccess(ccPair.id) : null,
    errorHandlingFetcher
  );
  // Below the Business tier groups do not exist, so neither request is sent
  // and admins alone manage the pair.
  const businessTier = useTierAtLeast(Tier.BUSINESS);
  const { data: userGroups } = useUserGroups(businessTier);
  // Who manages a pair is management data: a reader is refused it.
  const { data: manageRows, error: manageError } = useSWR<
    CCPairManageAccessRow[]
  >(
    businessTier ? SWR_KEYS.ccPairManageAccess(ccPair.id) : null,
    errorHandlingFetcher
  );
  const manageKnown = !businessTier || manageRows !== undefined;
  const memberCountOf = (groupId: number): string | undefined => {
    const group = userGroups?.find((candidate) => candidate.id === groupId);
    return group === undefined
      ? undefined
      : tGroups("memberCount", { count: group.users.length });
  };
  const fixedRows = (manageRows ?? []).filter((row) => row.is_fixed);
  const storedRows = (manageRows ?? []).filter((row) => !row.is_fixed);

  // Until the groups load, the summary names them without a count.
  const groupCount = dataAccess?.groups.length ?? null;
  const access: DocumentAccess =
    ccPair.access_type === "sync_restricted"
      ? {
          icon: SvgUserSync,
          label: tSettings("documentAccess.sync.title", { source }),
          summary:
            groupCount === null
              ? t("summary.syncRestrictedPending", { source })
              : t("summary.syncRestricted", { source, count: groupCount }),
        }
      : ccPair.access_type === "sync"
        ? {
            icon: SvgUserSync,
            label: tSettings("documentAccess.sync.title", { source }),
            summary: t("summary.sync", { source }),
          }
        : ccPair.access_type === "private"
          ? {
              icon: SvgUsers,
              label: tSettings("documentAccess.specificGroups.title"),
              summary:
                groupCount === null
                  ? t("summary.groupsPending")
                  : t("summary.groups", { count: groupCount }),
            }
          : {
              icon: SvgOrganization,
              label: tSettings("documentAccess.everyone.title"),
              summary: t("summary.everyone"),
            };
  const managedSummary = !manageKnown
    ? null
    : storedRows.length === 0
      ? t("summary.managedByAdmins")
      : t("summary.managedByGroups", { count: storedRows.length });

  const alwaysShared = (
    <Tag
      icon={SvgShare}
      title={tSettings("manageAccess.admins.alwaysShared")}
      color="gray"
    />
  );

  return (
    <Collapsible
      title={t("title")}
      description={markdown(
        format.list(
          managedSummary === null
            ? [access.summary]
            : [access.summary, managedSummary],
          { type: "unit" }
        )
      )}
      open={open}
      onOpenChange={setOpen}
      // The edit action shows with the content it edits.
      rightChildren={
        open &&
        onEdit !== null && (
          <Button prominence="secondary" icon={SvgEditBig} onClick={onEdit}>
            {t("editButton.label")}
          </Button>
        )
      }
    >
      <Card border="solid" rounding={4} padding={4}>
        <Section alignItems="stretch" gap={3} height="fit">
          <ContentAction
            title={tSettings("documentAccess.title")}
            description={tSettings("documentAccess.description")}
            sizePreset="main-ui"
            variant="section"
            padding={0}
            rightChildren={
              <Content
                icon={access.icon}
                title={access.label}
                sizePreset="secondary"
                variant="body"
                color="muted"
                width="fit"
              />
            }
          />
          {usesGroups && dataAccessError !== undefined && (
            <Text font="secondary-body" color="text-03">
              {t("groupsUnavailable")}
            </Text>
          )}
          {usesGroups &&
            dataAccess === undefined &&
            dataAccessError === undefined && <IconLoader size={16} />}
          {usesGroups && dataAccess !== undefined && (
            <Section
              flexDirection="row"
              justifyContent="start"
              gap={2}
              height="fit"
              wrap
            >
              {dataAccess.groups.map((group) => (
                <Tag
                  key={group.id}
                  icon={SvgUsers}
                  title={group.name}
                  value={memberCountOf(group.id)}
                  size="md"
                />
              ))}
            </Section>
          )}
          <Divider paddingParallel={0} paddingPerpendicular={0} />
          <ContentAction
            title={t("manageAccess.title")}
            description={tSettings("manageAccess.description")}
            sizePreset="main-ui"
            variant="section"
            padding={0}
          />
          {!manageKnown && manageError !== undefined && (
            <Text font="secondary-body" color="text-03">
              {t("manageAccess.unavailable")}
            </Text>
          )}
          {!manageKnown && manageError === undefined && (
            <IconLoader size={16} />
          )}
          {manageKnown && (
            <Section alignItems="stretch" gap={1} height="fit">
              {/* The groups with a global grant, else the admins they stand for. */}
              {fixedRows.length === 0 ? (
                <ContentAction
                  icon={SvgUserManage}
                  title={tSettings("manageAccess.admins.title")}
                  sizePreset="main-ui"
                  variant="section"
                  padding={1}
                  center
                  rightChildren={alwaysShared}
                />
              ) : (
                fixedRows.map((row) => (
                  <ContentAction
                    key={row.group_id}
                    icon={SvgUserManage}
                    title={row.group_name}
                    description={memberCountOf(row.group_id)}
                    sizePreset="main-ui"
                    variant="section"
                    padding={1}
                    center
                    rightChildren={alwaysShared}
                  />
                ))
              )}
              {storedRows.map((row) => (
                <ContentAction
                  key={row.group_id}
                  icon={SvgUsers}
                  title={row.group_name}
                  description={memberCountOf(row.group_id)}
                  sizePreset="main-ui"
                  variant="section"
                  padding={1}
                  center
                  rightChildren={
                    <Text font="secondary-action" color="text-03">
                      {tSettings(`manageAccess.role.${row.role}.label`)}
                    </Text>
                  }
                />
              ))}
            </Section>
          )}
        </Section>
      </Card>
    </Collapsible>
  );
}
