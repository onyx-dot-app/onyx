"use client";

import { useTranslations } from "next-intl";
import { SvgGlobe, SvgUser, SvgSlack, SvgKey } from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import Text from "@/refresh-components/texts/Text";
import type { UserRow } from "./interfaces";
import { AccountType } from "@/lib/types";

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
  const t = useTranslations("admin.users");
  const accountTypeLabels: Record<AccountType, string> = {
    [AccountType.STANDARD]: t("accountType.standard.label"),
    [AccountType.BOT]: t("accountType.bot.label"),
    [AccountType.EXT_PERM_USER]: t("accountType.extPermUser.label"),
    [AccountType.SERVICE_ACCOUNT]: t("accountType.serviceAccount.label"),
    [AccountType.ANONYMOUS]: t("accountType.anonymous.label"),
  };

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
        {accountTypeLabels[user.account_type]}
      </Text>
    </div>
  );
}
