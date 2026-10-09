"use client";

import { useTranslations } from "next-intl";
import { Button, SelectCard } from "@opal/components";
import { Content, Section } from "@opal/layouts";
import { SvgPlusCircle, SvgUserEdit } from "@opal/icons";
import type { DraftCredential } from "@/lib/credentials/types";
import { getCredentialDetails } from "@/lib/credentials/utils";
import type { ConfigurableSources } from "@/lib/connectors/types/source";

interface DraftAccountSummaryCardProps {
  /** The account typed into the form, which Create saves. */
  draft: DraftCredential;
  /** The source being set up. */
  source: ConfigurableSources;
  /** The source's display name, for an account with no name to show. */
  sourceName: string;
  /** Opens the account section again, with the new account's form. */
  onEdit: () => void;
}

/**
 * The typed account while the account section is folded. It is named by its
 * display name, else by the first value that tells it apart (such as its
 * email); secrets are never shown.
 */
export default function DraftAccountSummaryCard({
  draft,
  source,
  sourceName,
  onEdit,
}: DraftAccountSummaryCardProps) {
  const t = useTranslations("admin.connectorsList.add");
  const identifier: string | undefined = getCredentialDetails(
    draft,
    source
  ).fields.find(({ field }) => field.kind !== "secret")?.value;
  const title: string =
    draft.sharing.name ??
    identifier ??
    t("newAccountButton.label", { source: sourceName });

  return (
    <SelectCard
      state="filled"
      border="solid"
      rounding={4}
      padding={2}
      aria-label={title}
      data-testid="draft-account-summary"
      onClick={onEdit}
    >
      <Section
        flexDirection="row"
        alignItems="center"
        justifyContent="between"
        gap={4}
        width="full"
      >
        <Section alignItems="start" padding={2} width="full">
          <Content
            icon={SvgPlusCircle}
            title={title}
            suffix={t("draftSummary.newAccountSuffix")}
            sizePreset="main-ui"
            variant="section"
          />
        </Section>
        {/* Repeats the card's own action, so it leaves the tab order. */}
        <Button prominence="tertiary" rightIcon={SvgUserEdit} tabIndex={-1}>
          {t("draftSummary.editButton.label")}
        </Button>
      </Section>
    </SelectCard>
  );
}
