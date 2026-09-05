"use client";

import { useId, useState } from "react";
import { useTranslations } from "next-intl";
import useSWR from "swr";
import { Button, Card, CopyButton, Tag, Text } from "@opal/components";
import { Hoverable } from "@opal/core";
import { InputVertical, Section, toast } from "@opal/layouts";
import { SvgSimpleLoader } from "@opal/icons";
import {
  fetchDomainRecords,
  verifyDomainViaDns,
  type SSOLoginDomains,
  type SSOLoginDomainStatus,
} from "@/lib/sso/svc";
import { SWR_KEYS } from "@/lib/swr-keys";

interface SSODomainVerificationProps {
  domains: string[];
}

// Both stay plain text: the label is interpolated into a "label: " prefix, and
// the value is copied verbatim into the reader's DNS record.
interface RecordRowProps {
  label: string;
  value: string;
  copyable?: boolean;
}

function RecordRow({ label, value, copyable }: RecordRowProps) {
  const t = useTranslations("admin.ssoProviders.modals");
  const group = useId();
  const row = (
    <Section
      flexDirection="row"
      alignItems="center"
      justifyContent="between"
      height="fit"
      gap={2}
      padding={2}
      className={
        copyable ? "transition-colors hover:bg-background-tint-02" : undefined
      }
    >
      <div className="min-w-0 break-all">
        <Text font="main-ui-body" color="text-03" as="span">
          {t("domainVerification.record.labelPrefix", { label })}
        </Text>
        <Text font="main-ui-mono" color="text-04" as="span">
          {value}
        </Text>
      </div>
      {copyable && (
        <Hoverable.Item group={group} variant="appear-on-hover">
          <CopyButton getCopyText={() => value} size="sm" />
        </Hoverable.Item>
      )}
    </Section>
  );

  return copyable ? <Hoverable.Root group={group}>{row}</Hoverable.Root> : row;
}

interface DomainCardProps {
  status: SSOLoginDomainStatus;
  busy: boolean;
  onVerify: () => void;
}

function DomainCard({ status, busy, onVerify }: DomainCardProps) {
  const t = useTranslations("admin.ssoProviders.modals");

  return (
    <Card border="solid" rounding={4}>
      <Section flexDirection="column" alignItems="stretch" height="fit" gap={3}>
        <Section
          flexDirection="row"
          justifyContent="between"
          alignItems="center"
          height="fit"
          gap={2}
        >
          <Text font="main-ui-action" color="text-05" as="span">
            {status.domain}
          </Text>
          <Tag
            color={status.verified ? "green" : "amber"}
            title={
              status.verified
                ? t("domainVerification.status.verified")
                : t("domainVerification.status.pending")
            }
          />
        </Section>

        {status.verified ? (
          <Text font="secondary-body" color="text-03" as="span">
            {t("domainVerification.verifiedDescription")}
          </Text>
        ) : (
          <>
            <Text font="secondary-body" color="text-03" as="span">
              {t("domainVerification.pendingDescription")}
            </Text>
            <Card border="solid" rounding={3} padding={0}>
              <Section
                flexDirection="column"
                alignItems="stretch"
                height="fit"
                gap={0}
                className="[&>*+*]:border-t [&>*+*]:border-border-01"
              >
                <RecordRow
                  label={t("domainVerification.record.typeLabel")}
                  value="TXT"
                />
                {status.record_host && (
                  <RecordRow
                    label={t("domainVerification.record.nameLabel")}
                    value={status.record_host}
                    copyable
                  />
                )}
                {status.record_value && (
                  <RecordRow
                    label={t("domainVerification.record.valueLabel")}
                    value={status.record_value}
                    copyable
                  />
                )}
              </Section>
            </Card>
            <Section flexDirection="row" justifyContent="end" height="fit">
              <Button
                prominence="secondary"
                onClick={onVerify}
                disabled={busy || !status.claimed}
                icon={busy ? SvgSimpleLoader : undefined}
                tooltip={
                  status.claimed
                    ? undefined
                    : t("domainVerification.verifyButton.unclaimedTooltip")
                }
              >
                {t("domainVerification.verifyButton.label")}
              </Button>
            </Section>
          </>
        )}
      </Section>
    </Card>
  );
}

// Cloud only: a domain routes no one until the workspace proves ownership with a
// DNS TXT record. The record shows for an unsaved domain so it can be published
// early, but verifying it needs the saved claim the backend checks against.
export default function SSODomainVerification({
  domains,
}: SSODomainVerificationProps) {
  const t = useTranslations("admin.ssoProviders.modals");
  const { data, mutate, isLoading, error } = useSWR<SSOLoginDomains>(
    domains.length > 0 ? SWR_KEYS.adminSsoDomainRecords(domains) : null,
    () => fetchDomainRecords(domains)
  );
  const [busyDomain, setBusyDomain] = useState<string | null>(null);

  if (domains.length === 0) return null;

  async function verify(domain: string) {
    setBusyDomain(domain);
    try {
      await verifyDomainViaDns(domain);
      toast.success(t("domainVerification.verifiedToast.message", { domain }));
      // The backend persisted it, so apply the result locally before asking for
      // a refresh. A failed refresh then cannot report success as a failure or
      // leave the row sitting on its old pending state.
      await mutate(
        (current) =>
          current && {
            domains: current.domains.map((row) =>
              row.domain === domain
                ? {
                    ...row,
                    verified: true,
                    claimed: true,
                    record_host: null,
                    record_value: null,
                  }
                : row
            ),
          },
        { revalidate: true, rollbackOnError: false }
      ).catch(() => undefined);
    } catch (exc) {
      toast.error(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusyDomain(null);
    }
  }

  const rows = data?.domains ?? [];

  return (
    <InputVertical
      title={t("domainVerification.title")}
      description={t("domainVerification.description")}
      withLabel
    >
      <Section flexDirection="column" alignItems="stretch" height="fit" gap={3}>
        {/* Sits above the rows rather than replacing them: a failed refresh
            keeps the last rows, and showing them as current would hide that
            their verified state is no longer known. */}
        {error && (
          <Card border="solid" rounding={4}>
            <Section
              flexDirection="row"
              alignItems="center"
              justifyContent="between"
              height="fit"
              gap={2}
            >
              <Text font="main-ui-body" color="text-03" as="span">
                {rows.length > 0
                  ? t("domainVerification.refreshError.message")
                  : t("domainVerification.loadError.message")}
              </Text>
              <Button prominence="secondary" onClick={() => void mutate()}>
                {t("domainVerification.retryButton.label")}
              </Button>
            </Section>
          </Card>
        )}
        {isLoading && rows.length === 0 ? (
          <Section flexDirection="row" alignItems="center" height="fit" gap={2}>
            <SvgSimpleLoader className="text-text-03" />
            <Text font="main-ui-body" color="text-03">
              {t("domainVerification.loading.message")}
            </Text>
          </Section>
        ) : (
          rows.map((status) => (
            <DomainCard
              key={status.domain}
              status={status}
              busy={busyDomain === status.domain}
              onVerify={() => verify(status.domain)}
            />
          ))
        )}
      </Section>
    </InputVertical>
  );
}
