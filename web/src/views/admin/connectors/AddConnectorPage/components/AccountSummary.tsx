"use client";

import { useTranslations } from "next-intl";
import { Button } from "@opal/components";
import { Content, Section } from "@opal/layouts";
import { SvgPlusCircle, SvgUserEdit } from "@opal/icons";
import type { DraftCredential } from "@/lib/credentials/types";
import { useUser } from "@/providers/UserProvider";

interface AccountSummaryProps {
  /** The new account typed into the form, which Create saves. */
  draft: DraftCredential;
  /** The source's display name, for an account with no name to show. */
  sourceName: string;
}

/**
 * One row that names the new account: its display name, else the current
 * user's email. The new-account card shows it as its closed header once the
 * account is usable.
 */
export function AccountSummary({ draft, sourceName }: AccountSummaryProps) {
  const t = useTranslations("admin.connectorsList.add");
  const { user } = useUser();
  // Named like a saved account: its display name, else its creator (the
  // current user).
  const title: string =
    draft.sharing.name ??
    user?.email ??
    t("newAccountButton.label", { source: sourceName });

  return (
    // The action sits level with the title line.
    <Section
      flexDirection="row"
      alignItems="start"
      justifyContent="between"
      gap={4}
      width="full"
    >
      <Section alignItems="start" padding={2} width="full">
        <Content
          icon={SvgPlusCircle}
          title={title}
          suffix={t("accountSummary.newAccountSuffix")}
          sizePreset="main-ui"
          variant="section"
        />
      </Section>
      {/* Repeats its card's own action, so it leaves the tab order. */}
      <Button prominence="tertiary" rightIcon={SvgUserEdit} tabIndex={-1}>
        {t("accountSummary.editButton.label")}
      </Button>
    </Section>
  );
}
