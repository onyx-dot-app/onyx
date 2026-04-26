import { createTableColumns } from "@opal/components";
import { Content } from "@opal/layouts";
import { SvgUser, SvgUserManage, SvgGlobe } from "@opal/icons";
import { SvgSlack } from "@opal/logos";
import type { IconFunctionComponent } from "@opal/types";
import Text from "@/refresh-components/texts/Text";
import { AccountType, ACCOUNT_TYPE_LABELS, UserStatus } from "@/lib/types";
import type { ApiKeyDescriptor, MemberRow } from "./interfaces";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const PAGE_SIZE = 10;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

export function apiKeyToMemberRow(key: ApiKeyDescriptor): MemberRow {
  return {
    id: key.user_id,
    email: "Service Account",
    account_type: AccountType.SERVICE_ACCOUNT,
    status: UserStatus.ACTIVE,
    is_active: true,
    is_scim_synced: false,
    personal_name: key.api_key_name ?? "Unnamed Key",
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

function renderNameColumn(email: string, row: MemberRow) {
  return (
    <Content
      sizePreset="main-ui"
      variant="section"
      title={row.personal_name ?? email}
      description={row.personal_name ? email : undefined}
    />
  );
}

function renderAccountTypeColumn(_value: unknown, row: MemberRow) {
  const Icon =
    (row.account_type && ACCOUNT_TYPE_ICONS[row.account_type]) || SvgUser;
  return (
    <div className="flex flex-row items-center gap-1">
      <Icon className="w-4 h-4 text-text-03" />
      <Text as="span" mainUiBody text03>
        {row.account_type
          ? ACCOUNT_TYPE_LABELS[row.account_type] ?? row.account_type
          : "\u2014"}
      </Text>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Columns
// ---------------------------------------------------------------------------

export const tc = createTableColumns<MemberRow>();

export const baseColumns = [
  tc.qualifier(),
  tc.column("email", {
    header: "Name",
    weight: 25,
    cell: renderNameColumn,
  }),
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
    header: "Account Type",
    weight: 15,
    cell: renderAccountTypeColumn,
  }),
];

export const memberTableColumns = [
  ...baseColumns,
  tc.actions({ showSorting: false }),
];
