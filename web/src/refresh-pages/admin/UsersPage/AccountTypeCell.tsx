"use client";

import { SvgGlobe, SvgUser, SvgSlack, SvgKey } from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import Text from "@/refresh-components/texts/Text";
import type { UserRow } from "./interfaces";
import { AccountType, ACCOUNT_TYPE_LABELS } from "@/lib/types";

const ACCOUNT_TYPE_ICONS: Partial<Record<AccountType, IconFunctionComponent>> =
  {
    [AccountType.STANDARD]: SvgUser,
    [AccountType.BOT]: SvgSlack,
    [AccountType.EXT_PERM_USER]: SvgGlobe,
    [AccountType.SERVICE_ACCOUNT]: SvgKey,
  };

interface AccountTypeCellProps {
  user: UserRow;
  onMutate: () => void;
}

export default function AccountTypeCell({ user }: AccountTypeCellProps) {
  if (!user.account_type) {
    return (
      <Text as="span" secondaryBody text03>
        —
      </Text>
    );
  }

  const Icon = ACCOUNT_TYPE_ICONS[user.account_type] ?? SvgUser;

  return (
    <div className="flex flex-row items-center gap-1">
      <Icon className="w-4 h-4 text-text-03" />
      <Text as="span" mainUiBody text03>
        {ACCOUNT_TYPE_LABELS[user.account_type]}
      </Text>
    </div>
  );
}
