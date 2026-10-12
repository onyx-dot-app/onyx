"use client";

import { useTranslations } from "next-intl";
import { Button } from "@opal/components";
import { Content, Section } from "@opal/layouts";
import { SvgPlusCircle, SvgUserEdit } from "@opal/icons";
import type { DraftCredential } from "@/lib/credentials/types";
import { getCredentialDetails } from "@/lib/credentials/utils";
import type { ConfigurableSources } from "@/lib/connectors/types/source";

interface AccountSummaryProps {
  /** The new account typed into the form, which Create saves. */
  draft: DraftCredential;
  /** The source being set up. */
  source: ConfigurableSources;
  /** The source's display name, for an account with no name to show. */
  sourceName: string;
}

/**
 * One row that names the new account: its display name, else its first value
 * that is not a secret (such as its email). The new-account card shows it as
 * its closed header once the account is usable.
 */
export function AccountSummary({
  draft,
  source,
  sourceName,
}: AccountSummaryProps) {
  const t = useTranslations("admin.connectorsList.add");
  const title: string =
    draft.sharing.name ??
    getCredentialDetails(draft, source).fields.find(
      ({ field }) => field.kind !== "secret"
    )?.value ??
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
