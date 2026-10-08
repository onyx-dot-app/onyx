"use client";

import { useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import { Button, Modal, SelectCard, Text } from "@opal/components";
import { ContentAction, Section } from "@opal/layouts";
import {
  SvgAlertTriangle,
  SvgArrowRightCircle,
  SvgCheckSquare,
  SvgChevronDown,
  SvgChevronUp,
  SvgTrash,
} from "@opal/icons";
import type { Credential } from "@/lib/credentials/types";
import type { ConfigurableSources } from "@/lib/connectors/types/source";
import { getSourceMetadata } from "@/lib/sources";

interface AuthenticationAccountCardProps {
  /** The saved account this card shows. */
  credential: Credential<any>;
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
  const [expanded, setExpanded] = useState<boolean>(false);
  const [confirmingDelete, setConfirmingDelete] = useState<boolean>(false);

  const addedOn: string = format.dateTime(new Date(credential.time_created), {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });

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
        <Section gap={0} alignItems="stretch" width="full">
          <ContentAction
            icon={getSourceMetadata(source).icon}
            // Named by who created it; the account's own name stands in for
            // one with no creator.
            title={
              credential.user_email ?? credential.name ?? t("untitled.label")
            }
            suffix={t("sourceSuffix", { source: sourceName })}
            description={t("addedOn.label", { date: addedOn })}
            sizePreset="main-ui"
            variant="section"
            rightChildren={
              selected ? (
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
              )
            }
          />
          <Section flexDirection="row" justifyContent="end" width="full">
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
