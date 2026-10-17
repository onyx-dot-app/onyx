"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import useSWR from "swr";
import {
  Button,
  Card,
  Collapsible,
  Table,
  Text,
  type TableColumn,
} from "@opal/components";
import { Content, ContentAction, Section } from "@opal/layouts";
import {
  SvgEditBig,
  SvgOrganization,
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
import type { ConnectorManageRole } from "@/lib/connectors/accessType";
import { usesDataAccessGroups } from "@/lib/connectors/edit/prefill";
import { getSourceDisplayName } from "@/lib/connectors/utils";
import { useTierAtLeast } from "@/lib/tiers/hooks";
import { Tier } from "@/lib/tiers/types";

interface DocumentAccess {
  icon: IconFunctionComponent;
  label: string;
  summary: string;
}

interface ManageAccessItem {
  id: string;
  name: string;
  description: string | undefined;
  /** The avatar's glyph, or null for the admins' plain icon. */
  avatar: IconFunctionComponent | null;
  role: ConnectorManageRole;
  /** Granted globally, so it cannot be removed. */
  fixed: boolean;
}

interface ManageAvatarProps {
  icon: IconFunctionComponent | null;
}
/** The row's avatar: a dark circle with the glyph, or the admins' plain icon. */
function ManageAvatar({ icon: Icon }: ManageAvatarProps) {
  if (Icon === null) {
    return (
      <div className="flex h-7 w-7 items-center justify-center">
        <SvgUserManage size={16} className="stroke-text-03" aria-hidden />
      </div>
    );
  }
  return (
    <div className="flex h-7 w-7 items-center justify-center rounded-full bg-background-neutral-inverted-00">
      <Icon size={16} className="stroke-text-inverted-05" aria-hidden />
    </div>
  );
}

interface SharingPanelProps {
  children: React.ReactNode;
}
/** A white panel on the section's tinted card. */
function SharingPanel({ children }: SharingPanelProps) {
  return (
    <Card color="background-tint-00" rounding={3} padding={3}>
      <Section alignItems="stretch" gap={3} height="fit">
        {children}
      </Section>
    </Card>
  );
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
  const managerCountOf = (groupId: number): string | undefined => {
    const group = userGroups?.find((candidate) => candidate.id === groupId);
    return group === undefined
      ? undefined
      : tGroups("managerCount", { count: group.manager_ids.length });
  };
  const isDefaultGroup = (groupId: number): boolean =>
    userGroups?.find((candidate) => candidate.id === groupId)?.is_default ??
    false;
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

  // The groups with a global grant, else the admins they stand for. The
  // default (Admin) group shows as the admins.
  const manageItems: ManageAccessItem[] = [
    ...(fixedRows.length === 0
      ? [
          {
            id: "admins",
            name: tSettings("manageAccess.admins.title"),
            description: undefined,
            avatar: null,
            role: "editor" as const,
            fixed: true,
          },
        ]
      : fixedRows.map((row) => ({
          id: `fixed-${row.group_id}`,
          name: row.group_name,
          description: memberCountOf(row.group_id),
          avatar: isDefaultGroup(row.group_id) ? null : SvgUserManage,
          role: row.role,
          fixed: true,
        }))),
    ...storedRows.map((row) => ({
      id: `group-${row.group_id}`,
      name: row.group_name,
      description: managerCountOf(row.group_id),
      avatar: SvgUsers,
      role: row.role,
      fixed: false,
    })),
  ];
  const manageColumns: TableColumn<ManageAccessItem>[] = [
    {
      kind: "display",
      id: "avatar",
      width: { fixed: 44 },
      hideable: false,
      cell: (row) => <ManageAvatar icon={row.avatar} />,
    },
    {
      kind: "data",
      field: "name",
      title: t("manageAccess.title"),
      weight: 50,
      sortable: false,
      hideable: false,
      cell: (name, row) => (
        <Content
          title={name}
          description={row.description}
          sizePreset="main-ui"
          variant="section"
        />
      ),
    },
    {
      kind: "display",
      id: "role",
      width: { weight: 25 },
      hideable: false,
      cell: (row) => (
        <Section
          flexDirection="row"
          justifyContent="start"
          alignItems="center"
          gap={0.5}
          width="fit"
          height="fit"
        >
          <SvgEditBig size={16} className="stroke-text-03" aria-hidden />
          <Text font="main-ui-action" color="text-04">
            {tSettings(`manageAccess.role.${row.role}.label`)}
          </Text>
        </Section>
      ),
    },
    {
      kind: "display",
      id: "note",
      width: { weight: 25 },
      alignment: "right",
      hideable: false,
      cell: (row) =>
        row.fixed ? (
          <Section
            flexDirection="row"
            justifyContent="end"
            alignItems="center"
            gap={0.5}
            width="fit"
            height="fit"
          >
            <Text font="secondary-body" color="text-03">
              {tSettings("manageAccess.admins.alwaysShared")}
            </Text>
            <SvgUserManage size={16} className="stroke-text-03" aria-hidden />
          </Section>
        ) : null,
    },
  ];
  const AccessIcon = access.icon;

  return (
    <Collapsible
      title={t("title")}
      description={markdown(
        managedSummary === null
          ? t("summaryLine.access", { access: access.summary })
          : t("summaryLine.accessAndManaged", {
              access: access.summary,
              managed: managedSummary,
            })
      )}
      open={open}
      onOpenChange={setOpen}
      // The edit action shows with the content it edits.
      rightChildren={
        open &&
        onEdit !== null && (
          <Button prominence="tertiary" icon={SvgEditBig} onClick={onEdit}>
            {t("editButton.label")}
          </Button>
        )
      }
    >
      <Card color="background-tint-01" border="solid" rounding={4} padding={1}>
        <Section alignItems="stretch" gap={1} height="fit">
          <SharingPanel>
            <ContentAction
              title={tSettings("documentAccess.title")}
              description={tSettings("documentAccess.description")}
              sizePreset="main-ui"
              variant="section"
              padding={0}
              rightChildren={
                <Section
                  flexDirection="row"
                  alignItems="center"
                  gap={0.5}
                  width="fit"
                  height="fit"
                >
                  <AccessIcon
                    size={16}
                    className="stroke-text-04"
                    aria-hidden
                  />
                  <Text font="main-ui-action" color="text-04">
                    {access.label}
                  </Text>
                </Section>
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
                alignItems="stretch"
                gap={1}
                height="fit"
                wrap
              >
                {dataAccess.groups.map((group) => (
                  // Two tiles a row; each gives up half the gap.
                  <div
                    key={group.id}
                    className="min-w-0 basis-[calc(50%-0.125rem)] grow"
                  >
                    <Card color="background-tint-01" rounding={2} padding={2}>
                      <Content
                        icon={SvgUsers}
                        title={group.name}
                        description={memberCountOf(group.id)}
                        sizePreset="main-ui"
                        variant="section"
                      />
                    </Card>
                  </div>
                ))}
              </Section>
            )}
          </SharingPanel>
          <SharingPanel>
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
              <Table
                label={t("manageAccess.title")}
                items={manageItems}
                columns={manageColumns}
                getRowId={(row) => row.id}
                header={false}
                pageSize={false}
                prominence="secondary"
              />
            )}
          </SharingPanel>
        </Section>
      </Card>
    </Collapsible>
  );
}
