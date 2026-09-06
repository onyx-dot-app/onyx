import { useTranslations } from "next-intl";
import { createTableColumns } from "@opal/components";
import { Content } from "@opal/layouts";
import { SvgUser, SvgUserManage, SvgGlobe } from "@opal/icons";
import { SvgSlack } from "@opal/logos";
import type { IconFunctionComponent } from "@opal/types";
import Text from "@/refresh-components/texts/Text";
import { AccountType, UserStatus } from "@/lib/types";
import type { ApiKeyDescriptor, MemberRow } from "./interfaces";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const PAGE_SIZE = 10;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// Translated copy threaded in by the calling component, matching
// MemberColumnLabels below.
export interface ApiKeyMemberRowLabels {
  serviceAccountEmail: string;
  unnamedKey: string;
}

export function apiKeyToMemberRow(
  key: ApiKeyDescriptor,
  labels: ApiKeyMemberRowLabels
): MemberRow {
  return {
    id: key.user_id,
    email: labels.serviceAccountEmail,
    account_type: AccountType.SERVICE_ACCOUNT,
    is_admin: false,
    status: UserStatus.ACTIVE,
    is_active: true,
    is_scim_synced: false,
    craft_enabled: null,
    personal_name: key.api_key_name ?? labels.unnamedKey,
    created_at: null,
    updated_at: null,
    groups: [],
    api_key_display: key.api_key_display,
  };
}

// ---------------------------------------------------------------------------
// Account type icon mapping
// ---------------------------------------------------------------------------

const ACCOUNT_TYPE_ICONS: Partial<Record<AccountType, IconFunctionComponent>> =
  {
    [AccountType.STANDARD]: SvgUser,
    [AccountType.BOT]: SvgSlack,
    [AccountType.EXT_PERM_USER]: SvgGlobe,
    [AccountType.SERVICE_ACCOUNT]: SvgUserManage,
  };

// ---------------------------------------------------------------------------
// Column renderers
// ---------------------------------------------------------------------------

function AccountTypeCell({ row }: { row: MemberRow }) {
  const t = useTranslations("admin.users.accountType");
  const labels: Record<AccountType, string> = {
    [AccountType.STANDARD]: t("standard.label"),
    [AccountType.BOT]: t("bot.label"),
    [AccountType.EXT_PERM_USER]: t("extPermUser.label"),
    [AccountType.SERVICE_ACCOUNT]: t("serviceAccount.label"),
    [AccountType.ANONYMOUS]: t("anonymous.label"),
  };
  const Icon =
    (row.account_type && ACCOUNT_TYPE_ICONS[row.account_type]) || SvgUser;
  return (
    <div className="flex flex-row items-center gap-1">
      <Icon className="w-4 h-4 text-text-03" />
      <Text as="span" mainUiBody text03>
        {row.account_type
          ? (labels[row.account_type] ?? row.account_type)
          : "\u2014"}
      </Text>
    </div>
  );
}

function renderAccountTypeColumn(_value: unknown, row: MemberRow) {
  return <AccountTypeCell row={row} />;
}

// ---------------------------------------------------------------------------
// Columns
// ---------------------------------------------------------------------------

export const tc = createTableColumns<MemberRow>();

/** Translated copy for the member table. Columns are built outside React, so
 *  the calling component threads the strings in. */
export interface MemberColumnLabels {
  name: string;
  accountType: string;
  manager: string;
}

// `isManager` is optional — only the group edit page knows who manages a group.
function nameColumn(
  labels: MemberColumnLabels,
  isManager?: (row: MemberRow) => boolean
) {
  // Search/sort by a name+email composite so service accounts — whose email is a
  // "Service Account" placeholder — are findable by their API-key name.
  return tc.column(
    (row) => [row.personal_name, row.email].filter(Boolean).join(" "),
    {
      id: "name",
      header: labels.name,
      weight: 25,
      cell: (_searchValue, row) => (
        <Content
          sizePreset="main-ui"
          variant="section"
          title={row.personal_name ?? row.email}
          description={row.personal_name ? row.email : undefined}
          tag={
            isManager?.(row)
              ? { title: labels.manager, color: "blue" }
              : undefined
          }
        />
      ),
    }
  );
}

export function makeBaseColumns(
  labels: MemberColumnLabels,
  isManager?: (row: MemberRow) => boolean
) {
  return [
    tc.qualifier(),
    nameColumn(labels, isManager),
    tc.column("api_key_display", {
      header: "",
      weight: 15,
      enableSorting: false,
      cell: (value) =>
        value ? (
          <Text as="span" secondaryBody text03>
            {value}
          </Text>
        ) : null,
    }),
    tc.column("account_type", {
      header: labels.accountType,
      weight: 15,
      cell: renderAccountTypeColumn,
    }),
  ];
}

export function makeMemberTableColumns(labels: MemberColumnLabels) {
  return [...makeBaseColumns(labels), tc.actions({ showSorting: false })];
}
