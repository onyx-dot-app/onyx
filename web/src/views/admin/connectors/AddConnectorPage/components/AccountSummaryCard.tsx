"use client";

import { useFormatter, useTranslations } from "next-intl";
import { Button, SelectCard } from "@opal/components";
import { Content, Section } from "@opal/layouts";
import { SvgArrowExchange, SvgPlusCircle, SvgUserEdit } from "@opal/icons";
import type {
  DraftCredential,
  SimilarCredential,
} from "@/lib/credentials/types";
import { getCredentialDetails } from "@/lib/credentials/utils";
import type { ConfigurableSources } from "@/lib/connectors/types/source";
import { getSourceMetadata } from "@/lib/sources";

/** The account the folded account section stands for. */
export type SummarizedAccount =
  | { kind: "saved"; credential: SimilarCredential }
  | { kind: "draft"; draft: DraftCredential };

interface AccountSummaryProps {
  account: SummarizedAccount;
  /** The source being set up. */
  source: ConfigurableSources;
  /** The source's display name. */
  sourceName: string;
}

/**
 * One row that names the chosen account: a saved account, or the new account
 * typed into the form. A draft is named by its display name, else by its
 * first value that is not a secret (such as its email). The new-account card
 * shows it as its closed header; `AccountSummaryCard` wraps it for a saved
 * account.
 */
export function AccountSummary({
  account,
  source,
  sourceName,
}: AccountSummaryProps) {
  const t = useTranslations("admin.connectorsList.add");
  const format = useFormatter();

  const summary =
    account.kind === "saved"
      ? {
          icon: getSourceMetadata(source).icon,
          title:
            account.credential.user_email ??
            account.credential.name ??
            t("account.untitled.label"),
          suffix: t("account.sourceSuffix", { source: sourceName }),
          description: t("account.addedOn.label", {
            date: format.dateTime(new Date(account.credential.time_created), {
              year: "numeric",
              month: "2-digit",
              day: "2-digit",
            }),
          }),
          action: t("accountSummary.changeButton.label"),
          actionIcon: SvgArrowExchange,
        }
      : {
          icon: SvgPlusCircle,
          title:
            account.draft.sharing.name ??
            getCredentialDetails(account.draft, source).fields.find(
              ({ field }) => field.kind !== "secret"
            )?.value ??
            t("newAccountButton.label", { source: sourceName }),
          suffix: t("accountSummary.newAccountSuffix"),
          description: undefined,
          action: t("accountSummary.editButton.label"),
          actionIcon: SvgUserEdit,
        };

  return (
    <Section
      flexDirection="row"
      alignItems="center"
      justifyContent="between"
      gap={4}
      width="full"
    >
      <Section alignItems="start" padding={2} width="full">
        <Content
          icon={summary.icon}
          title={summary.title}
          suffix={summary.suffix}
          description={summary.description}
          sizePreset="main-ui"
          variant="section"
        />
      </Section>
      {/* Repeats its card's own action, so it leaves the tab order. */}
      <Button
        prominence="tertiary"
        rightIcon={summary.actionIcon}
        tabIndex={-1}
      >
        {summary.action}
      </Button>
    </Section>
  );
}

interface AccountSummaryCardProps {
  credential: SimilarCredential;
  /** The source being set up. */
  source: ConfigurableSources;
  /** The source's display name. */
  sourceName: string;
  /** Opens the account section again. */
  onExpand: () => void;
}

/**
 * The picked saved account while the account section is folded. Clicking it
 * opens the section.
 */
export default function AccountSummaryCard({
  credential,
  source,
  sourceName,
  onExpand,
}: AccountSummaryCardProps) {
  const title: string = credential.user_email ?? credential.name ?? "";
  return (
    <SelectCard
      state="filled"
      border="solid"
      rounding={4}
      padding={2}
      aria-label={title || undefined}
      data-testid="account-summary"
      onClick={onExpand}
    >
      <AccountSummary
        account={{ kind: "saved", credential }}
        source={source}
        sourceName={sourceName}
      />
    </SelectCard>
  );
}
