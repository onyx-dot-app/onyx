"use client";

import { useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import {
  Button,
  Card,
  Modal,
  OverflowText,
  SelectCard,
  Text,
} from "@opal/components";
import { Content, ContentAction, Section, toast } from "@opal/layouts";
import {
  SvgAlertTriangle,
  SvgArrowRightCircle,
  SvgCheckSquare,
  SvgChevronDown,
  SvgChevronUp,
  SvgLinkedDots,
  SvgPlay,
  SvgTrash,
  SvgUserKey,
} from "@opal/icons";
import type {
  Credential,
  CredentialCheckReport,
  SimilarCredential,
} from "@/lib/credentials/types";
import { useCredentialFieldCopy } from "@/lib/credentials/hooks";
import { getCredentialDetails } from "@/lib/credentials/utils";
import type { ConfigurableSources } from "@/lib/connectors/types/source";
import { getSourceMetadata } from "@/lib/sources";
import { useUser } from "@/providers/UserProvider";

interface DetailRowProps {
  label: string;
  value: string;
  /** Sets the value in the mono font, as for a secret. */
  mono?: boolean;
}
function DetailRow({ label, value, mono = false }: DetailRowProps) {
  return (
    <Section flexDirection="row" gap={4}>
      <Text font="main-ui-action" color="text-03" wordWrap="whitespace-nowrap">
        {label}
      </Text>
      {/* The value takes what the label leaves, and a long one is cut with
      its full text on hover. */}
      <div className="min-w-0 flex-1 text-end">
        <OverflowText
          as="p"
          font={mono ? "main-ui-mono" : "main-ui-body"}
          color="text-04"
        >
          {value}
        </OverflowText>
      </div>
    </Section>
  );
}

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
  /** The account's stored check report, or null if it was never checked. */
  checkReport: CredentialCheckReport | null;
  /** Starts the checks on this account; resolves once the run is queued. */
  onRerunChecks: (credential: Credential<any>) => Promise<void>;
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
  checkReport,
  onRerunChecks,
}: AuthenticationAccountCardProps) {
  const t = useTranslations("admin.connectorsList.add.account");
  const tCredentials = useTranslations("admin.credentials.delete");
  const tCredentialCopy = useTranslations("admin.credentials");
  const fieldCopy = useCredentialFieldCopy(source);
  const details = getCredentialDetails(credential, source);
  const format = useFormatter();
  const { user } = useUser();
  const [starting, setStarting] = useState<boolean>(false);
  const running: boolean = starting || checkReport?.run_status === "running";
  const lastChecked: string | null = checkReport?.report?.checked_at ?? null;
  const checkedAt: string | null = lastChecked
    ? format.dateTime(new Date(lastChecked), {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      })
    : null;

  async function rerunChecks() {
    setStarting(true);
    try {
      await onRerunChecks(credential);
    } catch {
      toast.error(t("rerunFailed.toast"));
    } finally {
      setStarting(false);
    }
  }
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
        state={selected ? "selected" : "filled"}
        border="solid"
        rounding={4}
        padding={2}
        data-testid="authentication-account"
        onClick={() => (selected ? onDeselect() : onSelect(credential))}
        expandedContent={
          <Section padding={2} width="full">
            <Card border="none" padding={2} rounding={3}>
              <Section gap={3} alignItems="stretch" width="full">
                <ContentAction
                  title={
                    checkedAt
                      ? t("lastTested.title", { date: checkedAt })
                      : t("notTested.title")
                  }
                  description={t("details.description")}
                  sizePreset="main-ui"
                  variant="section"
                  padding={0}
                  rightChildren={
                    <Section
                      flexDirection="row"
                      gap={1}
                      width="fit"
                      height="fit"
                    >
                      <Button
                        variant="danger"
                        prominence="tertiary"
                        icon={SvgTrash}
                        aria-label={t("deleteButton.label")}
                        onClick={() => setConfirmingDelete(true)}
                      />
                      <Button
                        prominence="secondary"
                        icon={SvgPlay}
                        disabled={running}
                        onClick={rerunChecks}
                      >
                        {running
                          ? t("rerunButton.runningLabel")
                          : t("rerunButton.label")}
                      </Button>
                    </Section>
                  }
                />
                {details.method && (
                  <DetailRow
                    label={t("authenticationType.label")}
                    value={tCredentialCopy(
                      `methods.labels.${details.method.label}`
                    )}
                  />
                )}
                {details.fields.map(({ key, field, value }) => (
                  <DetailRow
                    key={key}
                    label={fieldCopy(key).title}
                    value={value}
                    mono={field.kind === "secret"}
                  />
                ))}
              </Section>
            </Card>
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
