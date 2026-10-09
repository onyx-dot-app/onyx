"use client";

import { useFormatter, useTranslations } from "next-intl";
import { Button, SelectCard } from "@opal/components";
import { Content, Section } from "@opal/layouts";
import { SvgCheckSquare, SvgLinkedDots, SvgUserKey } from "@opal/icons";
import type { SimilarCredential } from "@/lib/credentials/types";
import type { ConfigurableSources } from "@/lib/connectors/types/source";
import { getSourceMetadata } from "@/lib/sources";
import { useUser } from "@/providers/UserProvider";

interface ExistingAccountSummaryCardProps {
  /** The picked saved account. */
  credential: SimilarCredential;
  /** The source being set up; it gives the card its icon. */
  source: ConfigurableSources;
  /** The source's display name, shown beside the account's name. */
  sourceName: string;
  /** Opens the account section again. */
  onExpand: () => void;
}

/**
 * The picked saved account while the account section is folded. It shows the
 * same details as its full card. Clicking it opens the section.
 */
export default function ExistingAccountSummaryCard({
  credential,
  source,
  sourceName,
  onExpand,
}: ExistingAccountSummaryCardProps) {
  const t = useTranslations("admin.connectorsList.add.account");
  const { user } = useUser();
  const format = useFormatter();
  const addedOn: string = format.dateTime(new Date(credential.time_created), {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
  // The creator, by display name where they set one, as on the full card.
  const ownerName: string | null =
    credential.user_id === null
      ? null
      : (credential.user_personal_name ?? credential.user_email);
  const isOwnAccount: boolean = user !== null && credential.user_id === user.id;
  const title: string =
    credential.user_email ?? credential.name ?? t("untitled.label");

  return (
    <SelectCard
      // The full card's details, without its selected look.
      state="filled"
      border="solid"
      rounding={4}
      padding={2}
      aria-label={title}
      data-testid="existing-account-summary"
      onClick={onExpand}
    >
      <Section flexDirection="row" alignItems="stretch" gap={4} width="full">
        <Section alignItems="start" gap={0} padding={2} width="full">
          <Content
            icon={getSourceMetadata(source).icon}
            title={title}
            suffix={t("sourceSuffix", { source: sourceName })}
            description={t("addedOn.label", { date: addedOn })}
            sizePreset="main-ui"
            variant="section"
          />
          {/* One-sided padding, which Section's own padding overrides. */}
          <div className="flex flex-row gap-4 ps-5.5 pt-2">
            <Content
              icon={SvgLinkedDots}
              title={t("usedBy.label", { count: credential.usages.length })}
              sizePreset="secondary"
              variant="body"
              color="muted"
              width="fit"
            />
            {ownerName !== null && (
              <Content
                icon={SvgUserKey}
                title={
                  isOwnAccount ? t("owner.you", { name: ownerName }) : ownerName
                }
                sizePreset="secondary"
                variant="body"
                color="muted"
                width="fit"
              />
            )}
          </div>
        </Section>
        <Section alignItems="end" width="fit">
          {/* A label, not an action: the card's click opens the section. */}
          <Button
            variant="action"
            prominence="tertiary"
            rightIcon={SvgCheckSquare}
            tabIndex={-1}
          >
            {t("selected.label")}
          </Button>
        </Section>
      </Section>
    </SelectCard>
  );
}
