"use client";

import { useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import { Button, Card } from "@opal/components";
import { Content, ContentAction, Section, toast } from "@opal/layouts";
import { SvgUserEdit } from "@opal/icons";
import type { CCPairFullInfo } from "@/lib/connectors/types";
import { isEditableSource } from "@/lib/connectors/edit/editable";
import {
  useCredentialCheckReports,
  useCredentialSetup,
} from "@/lib/credentials/hooks";
import type { SimilarCredential } from "@/lib/credentials/types";
import {
  getSourceDisplayName,
  getSourceMetadata,
} from "@/lib/connectors/utils";
import { useTierAtLeast } from "@/lib/tiers/hooks";
import { Tier } from "@/lib/tiers/types";
import AuthenticationAccountCard from "@/views/admin/connectors/AddConnectorPage/components/AuthenticationAccountCard";

export interface AuthenticationAccountSectionProps {
  ccPair: CCPairFullInfo;
  /** Shows the edit action, which opens the connector form. */
  onEdit: (() => void) | null;
}

/** The account the connector signs in with: the saved-account card when it is listed for the caller and the source has a form, else a plain one. */
export default function AuthenticationAccountSection({
  ccPair,
  onEdit,
}: AuthenticationAccountSectionProps) {
  const t = useTranslations("admin.connector.account");
  const tAccount = useTranslations("admin.connectorsList.add.account");
  const tAdd = useTranslations("admin.connectorsList.add");
  const format = useFormatter();
  const source = ccPair.connector.source;
  const sourceName = getSourceDisplayName(source) ?? source;
  const { credentials, remove, saveSharing } = useCredentialSetup(source);
  const checkReports = useCredentialCheckReports(source);
  const businessTier = useTierAtLeast(Tier.BUSINESS);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const toggleDetails = () => setDetailsOpen((open) => !open);

  const credential: SimilarCredential | null =
    credentials?.find((saved) => saved.id === ccPair.credential.id) ?? null;
  const editAction =
    onEdit === null ? null : (
      <Button
        prominence="tertiary"
        rightIcon={SvgUserEdit}
        onClick={(event) => {
          // The card's own click opens its details.
          event.stopPropagation();
          onEdit();
        }}
      >
        {t("editButton.label")}
      </Button>
    );

  return (
    <Section alignItems="stretch" gap={3} height="fit">
      <Content title={t("title")} sizePreset="main-content" variant="section" />
      {credential !== null && isEditableSource(source) ? (
        <AuthenticationAccountCard
          credential={credential}
          source={source}
          sourceName={sourceName}
          selected={false}
          selectable
          // The whole card opens and closes the details.
          onSelect={toggleDetails}
          onDeselect={toggleDetails}
          action={editAction}
          onDelete={async () => {
            const error = await remove(credential, tAdd("unknownError.toast"));
            if (error !== null) toast.error(error);
          }}
          detailsOpen={detailsOpen}
          onDetailsOpenChange={setDetailsOpen}
          checkReport={checkReports.reportFor(credential.id)}
          onRerunChecks={() => checkReports.rerun(credential.id)}
          groupsLocked={!businessTier}
          onSaveAccount={(update) => saveSharing(credential.id, update)}
        />
      ) : (
        <Card border="solid" rounding={4} padding={2}>
          <ContentAction
            icon={getSourceMetadata(source).icon}
            title={
              ccPair.credential.name ||
              ccPair.credential.user_email ||
              tAccount("untitled.label")
            }
            suffix={tAccount("sourceSuffix", { source: sourceName })}
            description={tAccount("addedOn.label", {
              date: format.dateTime(new Date(ccPair.credential.time_created), {
                year: "numeric",
                month: "2-digit",
                day: "2-digit",
              }),
            })}
            sizePreset="main-ui"
            variant="section"
            padding={0}
            rightChildren={editAction ?? undefined}
          />
        </Card>
      )}
    </Section>
  );
}
