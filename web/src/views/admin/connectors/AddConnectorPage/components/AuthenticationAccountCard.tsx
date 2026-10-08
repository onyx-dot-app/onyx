"use client";

import { useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import { Button, Modal, SelectCard, Text } from "@opal/components";
import { Content, Section } from "@opal/layouts";
import {
  SvgAlertTriangle,
  SvgArrowRightCircle,
  SvgCheckSquare,
  SvgChevronDown,
  SvgChevronUp,
  SvgLinkedDots,
  SvgTrash,
  SvgUserKey,
} from "@opal/icons";
import type { Credential, SimilarCredential } from "@/lib/credentials/types";
import type { ConfigurableSources } from "@/lib/connectors/types/source";
import { getSourceMetadata } from "@/lib/sources";
import { useUser } from "@/providers/UserProvider";

interface AuthenticationAccountCardProps {
  /** The saved account this card shows. */
  credential: SimilarCredential;
  /** The source being set up; it gives the card its icon. */
  source: ConfigurableSources;
  /** The source's display name, shown beside the account's name. */
  sourceName: string;
  /** Whether the connector will use this account. */
  selected: boolean;
  /** Called when the user picks this account. */
  onSelect: (credential: Credential<any>) => void;
  /** Called when the user picks the selected account again, to drop it. */
  onDeselect: () => void;
  /** Called once the user confirms the deletion. */
  onDelete: (credential: Credential<any>) => void;
}

/**
 * One saved account in the Authentication Account section. The whole card
 * picks the account, or drops it when it is already picked; the chevron
 * opens the details below it.
 */
export default function AuthenticationAccountCard({
  credential,
  source,
  sourceName,
  selected,
  onSelect,
  onDeselect,
  onDelete,
}: AuthenticationAccountCardProps) {
  const t = useTranslations("admin.connectorsList.add.account");
  const tCredentials = useTranslations("admin.credentials.delete");
  const format = useFormatter();
  const { user } = useUser();
  const [expanded, setExpanded] = useState<boolean>(false);
  const [confirmingDelete, setConfirmingDelete] = useState<boolean>(false);

  const addedOn: string = format.dateTime(new Date(credential.time_created), {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });

  // The creator, by display name where they set one. An account with no
  // creator shows no owner.
  const ownerName: string | null =
    credential.user_id === null
      ? null
      : (credential.user_personal_name ?? credential.user_email);
  const isOwnAccount: boolean = user !== null && credential.user_id === user.id;

  return (
    <>
      {confirmingDelete && (
        <Modal open onOpenChange={() => setConfirmingDelete(false)}>
          <Modal.Content width="sm" height="sm">
            <Modal.Header
              icon={SvgAlertTriangle}
              title={tCredentials("confirmTitle")}
              onClose={() => setConfirmingDelete(false)}
            />
            <Modal.Body>
              <Text font="main-ui-body" color="text-04">
                {tCredentials("confirmBody.message")}
              </Text>
            </Modal.Body>
            <Modal.Footer>
              <Button
                variant="danger"
                onClick={() => {
                  setConfirmingDelete(false);
                  onDelete(credential);
                }}
              >
                {tCredentials("confirmButton.label")}
              </Button>
              <Button
                prominence="secondary"
                onClick={() => setConfirmingDelete(false)}
              >
                {tCredentials("cancelButton.label")}
              </Button>
            </Modal.Footer>
          </Modal.Content>
        </Modal>
      )}

      <SelectCard
        expandable
        expanded={expanded}
        expandableContentHeight="full"
        state={selected ? "selected" : "empty"}
        border="solid"
        rounding={4}
        padding={2}
        data-testid="authentication-account"
        onClick={() => (selected ? onDeselect() : onSelect(credential))}
        expandedContent={
          <Section
            flexDirection="row"
            justifyContent="start"
            padding={4}
            width="full"
          >
            <Button
              variant="danger"
              prominence="secondary"
              icon={SvgTrash}
              // The connector is about to use the selected account.
              disabled={selected}
              onClick={() => setConfirmingDelete(true)}
            >
              {t("deleteButton.label")}
            </Button>
          </Section>
        }
      >
        <Section flexDirection="row" alignItems="stretch" gap={4} width="full">
          <Section alignItems="start" gap={0} padding={2} width="full">
            <Content
              icon={getSourceMetadata(source).icon}
              // Named by who created it; the account's own name stands in
              // for one with no creator.
              title={
                credential.user_email ?? credential.name ?? t("untitled.label")
              }
              suffix={t("sourceSuffix", { source: sourceName })}
              description={t("addedOn.label", { date: addedOn })}
              sizePreset="main-ui"
              variant="section"
            />
            <div className="flex flex-row gap-4 ps-5 pt-2">
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
                    isOwnAccount
                      ? t("owner.you", { name: ownerName })
                      : ownerName
                  }
                  sizePreset="secondary"
                  variant="body"
                  color="muted"
                  width="fit"
                />
              )}
            </div>
          </Section>
          <Section
            alignItems="end"
            justifyContent="between"
            gap={1}
            width="fit"
          >
            {selected ? (
              <Button
                variant="action"
                prominence="tertiary"
                rightIcon={SvgCheckSquare}
                tabIndex={-1}
              >
                {t("selected.label")}
              </Button>
            ) : (
              // Repeats the card's own action, so it leaves the tab order.
              <Button
                prominence="tertiary"
                rightIcon={SvgArrowRightCircle}
                tabIndex={-1}
              >
                {t("useButton.label")}
              </Button>
            )}
            <Button
              icon={expanded ? SvgChevronUp : SvgChevronDown}
              prominence="tertiary"
              aria-label={
                expanded
                  ? t("collapseButton.ariaLabel")
                  : t("expandButton.ariaLabel")
              }
              aria-expanded={expanded}
              onClick={(event) => {
                // Opens the details; it does not pick the account.
                event.stopPropagation();
                setExpanded((open) => !open);
              }}
            />
          </Section>
        </Section>
      </SelectCard>
    </>
  );
}
